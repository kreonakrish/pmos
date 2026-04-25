"""PMOS Permission Registry — Orchestrator.

Mirror of services/gateway/app/middleware/permissions.ts. Lives next to the
FastAPI app so dependency injection can reference it without a cross-service
import.

Permission names match infra/mysql/auth_schema.sql exactly.

The orchestrator only enforces a subset of routes — the ones reachable
directly from the gateway via HTTP. Internal pipeline calls are not gated
because they originate from the orchestrator itself, not from a user.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class RouteRule:
    """A single (path, method) → permission(s) gate."""

    path: str                       # FastAPI-style path with {placeholders}
    methods: Tuple[str, ...]        # ('POST',), ('GET','HEAD'), ()=all
    any_of: Tuple[str, ...]         # user must hold AT LEAST ONE


# ---------------------------------------------------------------------------
# Mutating routes — fail closed on DB outage
# ---------------------------------------------------------------------------
PERMISSION_REQUIREMENTS_WRITE: List[RouteRule] = [
    # ── Catalog mutations ─────────────────────────────────────────────────
    RouteRule("/v1/catalog/crawlers",                     ("POST",), ("catalog.write",)),
    RouteRule("/v1/catalog/crawlers/{crawler_id}/run",    ("POST",), ("catalog.write",)),
    RouteRule("/v1/catalog/mapping-decisions/{decision_id}/review",
              ("POST",), ("catalog.write",)),

    # ── Conversations / chat ──────────────────────────────────────────────
    RouteRule("/v1/orchestrator/chat",                    ("POST",), ("conversations.write",)),
    RouteRule("/v1/orchestrator/conversations",           ("POST",), ("conversations.write",)),
    RouteRule("/v1/orchestrator/conversations/{conversation_id}",
              ("PATCH", "PUT"), ("conversations.write",)),
    RouteRule("/v1/orchestrator/conversations/{conversation_id}",
              ("DELETE",), ("conversations.write",)),
    RouteRule("/v1/orchestrator/conversations/{conversation_id}/messages",
              ("POST",), ("conversations.write",)),
    RouteRule("/v1/orchestrator/conversations/{conversation_id}/feedback",
              ("POST",), ("conversations.write",)),

    # ── Job control ───────────────────────────────────────────────────────
    RouteRule("/v1/orchestrator/jobs/{graph_id}/resume",  ("POST",), ("jobs.write",)),

    # ── ML governance write surfaces ──────────────────────────────────────
    RouteRule("/v1/ml/sops/proposals/{proposal_id}/promote",
              ("POST",), ("models.deploy",)),
    RouteRule("/v1/ml/sops/proposals/{proposal_id}/reject",
              ("POST",), ("models.write",)),
]

# ---------------------------------------------------------------------------
# Read-only routes that should still be gated — fail open on DB outage
# ---------------------------------------------------------------------------
PERMISSION_REQUIREMENTS_READ: List[RouteRule] = [
    # Catalog reads (frontend gates with catalog.read)
    RouteRule("/v1/catalog/crawlers",                     ("GET",), ("catalog.read",)),
    RouteRule("/v1/catalog/crawlers/{crawler_id}/runs",   ("GET",), ("catalog.read",)),
    RouteRule("/v1/catalog/assets",                       ("GET",), ("catalog.read",)),
    RouteRule("/v1/catalog/ontology",                     ("GET",), ("catalog.read",)),
    RouteRule("/v1/catalog/mapping-decisions",            ("GET",), ("catalog.read",)),
    RouteRule("/v1/catalog/mapping-decisions/summary",    ("GET",), ("catalog.read",)),
    RouteRule("/v1/catalog/lineage",                      ("GET",), ("catalog.read",)),
    RouteRule("/v1/catalog/schema-graph",                 ("GET",), ("catalog.read",)),

    # Governance reads
    RouteRule("/v1/governance/traces",                    ("GET",), ("models.read", "ml_insights.read")),
    RouteRule("/v1/governance/traces/{trace_id}",         ("GET",), ("models.read", "ml_insights.read")),
    RouteRule("/v1/governance/traces/by-conversation/{conversation_id}",
              ("GET",), ("models.read", "ml_insights.read")),

    # ML insights reads
    RouteRule("/v1/ml/bandits/summary",                   ("GET",), ("ml_insights.read",)),
    RouteRule("/v1/ml/bandits/state",                     ("GET",), ("ml_insights.read",)),
    RouteRule("/v1/ml/bandits/decisions",                 ("GET",), ("ml_insights.read",)),
    RouteRule("/v1/ml/bandits/convergence",               ("GET",), ("ml_insights.read",)),
    RouteRule("/v1/ml/embeddings/summary",                ("GET",), ("ml_insights.read",)),
    RouteRule("/v1/ml/embeddings/projection",             ("GET",), ("ml_insights.read",)),
    RouteRule("/v1/ml/embeddings/similar",                ("GET",), ("ml_insights.read",)),
    RouteRule("/v1/ml/learned-scorer/summary",            ("GET",), ("ml_insights.read",)),
    RouteRule("/v1/ml/learned-scorer/predictions",        ("GET",), ("ml_insights.read",)),
    RouteRule("/v1/ml/sops/proposals",                    ("GET",), ("ml_insights.read",)),
]

# ---------------------------------------------------------------------------
# Routes intentionally NOT gated (auth still required, but no specific perm):
#
#   - /health, /metrics                       → public
#   - /v1/orchestrator/conversations          (GET list) → returns the
#       caller's data; orchestrator filters by user_id downstream
#   - /v1/orchestrator/conversations/{id}     (GET)      → same
#   - /v1/orchestrator/conversations/{id}/messages (GET) → same
#   - /v1/orchestrator/jobs, /v1/orchestrator/jobs/{id}  → user-scoped
#   - /v1/orchestrator/tasks, /v1/orchestrator/tasks/{id}→ user-scoped
#   - /v1/orchestrator/graph/tasks            → graph.read (every default
#       role has it; gating is noise)
#   - /v1/sandbox/*                           → dev tooling only
#
# Re-evaluate after a security review.
# ---------------------------------------------------------------------------

ALL_GATED_RULES: List[RouteRule] = (
    PERMISSION_REQUIREMENTS_WRITE + PERMISSION_REQUIREMENTS_READ
)

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
