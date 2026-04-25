"""Server-side RBAC enforcement (orchestrator).

Companion to ``services/gateway/app/middleware/rbac.ts``. Provides FastAPI
``Depends`` factories that look up the caller's permission set from MySQL
and 403 if the required permission is missing.

Identity source
---------------
The gateway is the trust boundary: it verifies the JWT and forwards the
resolved user identity to downstream services as the ``x-user-id`` header
(numeric DB id). The orchestrator does NOT re-verify the JWT — it just
trusts the gateway-set header. If a request arrives with no ``x-user-id``,
we treat it as unauthenticated (401) on a gated route.

Failure mode
------------
- MySQL unavailable + mutating route (POST/PUT/PATCH/DELETE)
    → fail CLOSED (deny).
- MySQL unavailable + read-only route (GET/HEAD)
    → fail OPEN with a warning so the system stays observable.
- Missing ``x-user-id`` on a gated route → 401 (not 403).
- ``x-api-key`` set with no ``x-user-id`` → bypass RBAC. The gateway's
  authMiddleware already vetted the API key.

Caching
-------
A 30-second in-process LRU keeps DB round-trips off the hot path. Bypass
the cache via ``_clear_rbac_cache()`` from tests.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Dict, Optional, Set, Tuple

import mysql.connector
from fastapi import HTTPException, Request

from app.config import settings
from app.utils.logger import logger

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
_PERMISSION_CACHE_TTL_SEC = 30.0
_PERMISSION_CACHE_MAX = 500
_cache_lock = threading.Lock()
# uid → (perms, expires_at)
_cache: Dict[int, Tuple[Set[str], float]] = {}


def _cache_get(uid: int) -> Optional[Set[str]]:
    with _cache_lock:
        hit = _cache.get(uid)
        if not hit:
            return None
        perms, expires = hit
        if expires < time.monotonic():
            _cache.pop(uid, None)
            return None
        # Touch for LRU
        _cache.pop(uid, None)
        _cache[uid] = (perms, expires)
        return perms


def _cache_set(uid: int, perms: Set[str]) -> None:
    with _cache_lock:
        if len(_cache) >= _PERMISSION_CACHE_MAX:
            # Evict oldest
            oldest_key = next(iter(_cache))
            _cache.pop(oldest_key, None)
        _cache[uid] = (perms, time.monotonic() + _PERMISSION_CACHE_TTL_SEC)


def _clear_rbac_cache() -> None:
    """Test hook."""
    with _cache_lock:
        _cache.clear()


# ---------------------------------------------------------------------------
# DB lookup
# ---------------------------------------------------------------------------
def _conn():
    """Same shape as routes/catalog.py:_conn() so we hit one place to swap."""
    return mysql.connector.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_db,
        connection_timeout=5,
    )


def load_permissions_for_user(uid: int) -> Set[str]:
    """Read the user's permission set from MySQL, with caching.

    Raises on DB error so the caller can decide on the fail-open / fail-closed
    posture per route.
    """
    cached = _cache_get(uid)
    if cached is not None:
        return cached

    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT p.name
              FROM permissions p
              JOIN role_permissions rp ON rp.permission_id = p.id
              JOIN user_roles ur        ON ur.role_id = rp.role_id
             WHERE ur.user_id = %s
            """,
            (uid,),
        )
        rows = cur.fetchall() or []
    finally:
        try:
            conn.close()
        except Exception:
            pass
    perms = {r[0] for r in rows if r and r[0]}
    _cache_set(uid, perms)
    return perms


# ---------------------------------------------------------------------------
# Identity extraction
# ---------------------------------------------------------------------------
def _extract_uid(request: Request) -> Optional[int]:
    """Return the caller's numeric user id, or ``None`` if absent.

    A returned value of ``-1`` is the "API-key bypass" sentinel — same
    convention as the gateway middleware.
    """
    if request.headers.get("x-api-key"):
        return -1
    raw = request.headers.get("x-user-id")
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Public API: dependency factories
# ---------------------------------------------------------------------------
_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def _trace_id(request: Request) -> str:
    return request.headers.get("x-request-id") or "no-trace"


def require_permission(perm: str) -> Callable[[Request], None]:
    """FastAPI ``Depends`` factory: requires the caller to hold ``perm``.

    Usage::

        @router.post(
            "/crawlers",
            dependencies=[Depends(require_permission("catalog.write"))],
        )
        async def create_crawler(...): ...
    """

    def _dep(request: Request) -> None:
        _enforce(request, any_of=(perm,))

    _dep.__name__ = f"require_permission_{perm.replace('.', '_')}"
    return _dep


def require_any_permission(*perms: str) -> Callable[[Request], None]:
    """FastAPI ``Depends`` factory: caller must hold at least one of perms."""

    def _dep(request: Request) -> None:
        _enforce(request, any_of=perms)

    _dep.__name__ = "require_any_permission_" + "_".join(p.replace(".", "_") for p in perms)
    return _dep


# ---------------------------------------------------------------------------
# Core enforcement
# ---------------------------------------------------------------------------
def _enforce(request: Request, any_of: Tuple[str, ...]) -> None:
    trace_id = _trace_id(request)
    method = (request.method or "GET").upper()
    is_mutating = method in _MUTATING

    uid = _extract_uid(request)

    if uid is None:
        # No identity at all — 401 even on read routes.
        logger.warning(
            "rbac_no_identity",
            layer="middleware",
            method=method,
            path=str(request.url.path),
            trace_id=trace_id,
        )
        raise HTTPException(
            status_code=401,
            detail={
                "error": "Not authenticated; missing x-user-id",
                "code": "AUTH_FAILED",
                "trace_id": trace_id,
            },
        )

    if uid == -1:
        # API-key bypass — already authenticated by the gateway.
        return

    try:
        perms = load_permissions_for_user(uid)
    except mysql.connector.Error as exc:
        logger.error(
            "rbac_db_unavailable",
            layer="middleware",
            method=method,
            path=str(request.url.path),
            trace_id=trace_id,
            uid=uid,
            error=str(exc),
        )
        if is_mutating:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "RBAC unavailable; denying mutation",
                    "code": "FORBIDDEN",
                    "trace_id": trace_id,
                },
            )
        # Read route → fail open
        logger.warning(
            "rbac_fail_open_read",
            layer="middleware",
            method=method,
            path=str(request.url.path),
            trace_id=trace_id,
            uid=uid,
        )
        return

    if not any(p in perms for p in any_of):
        logger.warning(
            "rbac_denied",
            layer="middleware",
            method=method,
            path=str(request.url.path),
            trace_id=trace_id,
            uid=uid,
            any_of=list(any_of),
        )
        raise HTTPException(
            status_code=403,
            detail={
                "error": f"Access denied — requires one of: {', '.join(any_of)}",
                "code": "FORBIDDEN",
                "missing": list(any_of),
                "trace_id": trace_id,
            },
        )
