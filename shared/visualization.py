"""Visualization spec + chart-type heuristic.

Used by the orchestrator to attach chart specs to assistant messages when a
deterministic Report runs. The frontend (client/src/components/Chat/
VisualizationBlock.tsx) consumes these and renders bar/line/pie/area/table.

Wire format kept as plain dicts so it survives JSON serialization to
``messages.metadata`` and back through the chat API.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple


CHART_TYPES = ("bar", "line", "pie", "area", "table")
MAX_CHART_ROWS = 200


def _is_date_like(v: Any) -> bool:
    if isinstance(v, (datetime, date)):
        return True
    if isinstance(v, str):
        # Loose ISO / common-format detection.
        return bool(
            re.match(
                r"^\d{4}-\d{2}(-\d{2})?(T\d{2}:\d{2}(:\d{2})?)?$|"
                r"^\d{4}-Q[1-4]$|^\d{4}$|^\d{4}/\d{2}/\d{2}$",
                v.strip(),
            )
        )
    return False


def _is_numeric(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float, Decimal)):
        return True
    if isinstance(v, str):
        try:
            float(v)
            return True
        except ValueError:
            return False
    return False


def _coerce_value(v: Any) -> Any:
    """Make values JSON-serializable for the wire payload.

    Dates → ISO strings; Decimal → float; everything else passed through.
    """
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        try:
            return float(v)
        except Exception:
            return str(v)
    if isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


def _looks_like_year(v: Any) -> bool:
    """4-digit integer in [1900, 2100] — treat as a temporal dimension."""
    try:
        n = float(v)
        if n != int(n):
            return False
        n = int(n)
        return 1900 <= n <= 2100
    except (TypeError, ValueError):
        return False


def _column_kinds(
    rows: Sequence[Dict[str, Any]], col_names: Sequence[str]
) -> Dict[str, str]:
    """Classify each column as 'numeric' | 'date' | 'category'.

    Skips null values when classifying. Empty columns default to 'category'.
    Numeric columns whose values all look like 4-digit years (1900-2100) AND
    whose name hints at a year (year/yr/fy/fiscal/period) are promoted to
    ``date`` so a year-keyed report renders as a bar/line, not as a
    fallback table.
    """
    kinds: Dict[str, str] = {}
    for c in col_names:
        non_null = [r.get(c) for r in rows if r.get(c) is not None]
        if not non_null:
            kinds[c] = "category"
            continue
        if all(_is_date_like(v) for v in non_null):
            kinds[c] = "date"
        elif all(_is_numeric(v) for v in non_null):
            name_hints_year = any(
                tok in c.lower() for tok in ("year", "yr", "fy", "fiscal", "period")
            )
            if name_hints_year and all(_looks_like_year(v) for v in non_null):
                kinds[c] = "date"
            else:
                kinds[c] = "numeric"
        else:
            kinds[c] = "category"
    return kinds


def infer_chart(
    rows: Sequence[Dict[str, Any]],
    col_names: Sequence[str],
    *,
    title: str = "",
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Pick a chart type from the data shape.

    Rules (first match wins):
      1. 1 date col + ≥1 numeric col  → ``line`` (x = date, y = numerics)
      2. 1 category col + 1 numeric col + ≤6 rows + values look like shares → ``pie``
      3. 1 category col + ≥1 numeric col + ≤30 rows  → ``bar``
      4. fallback                                    → ``table`` (data still attached)

    Returns a Visualization dict matching the frontend contract:
      { type, title, description, x_field, y_fields, data, inferred_from,
        truncated_from }
    """
    rows = list(rows or [])
    col_names = list(col_names or [])
    truncated_from: Optional[int] = None
    if len(rows) > MAX_CHART_ROWS:
        truncated_from = len(rows)
        rows = rows[:MAX_CHART_ROWS]

    # Coerce data once; the frontend can JSON-stringify safely.
    data = [
        {c: _coerce_value(r.get(c)) for c in col_names} for r in rows
    ]

    if not col_names or not data:
        return {
            "type": "table",
            "title": title or "Result",
            "description": description,
            "x_field": col_names[0] if col_names else "",
            "y_fields": col_names[1:] if len(col_names) > 1 else [],
            "data": data,
            "inferred_from": "empty",
            "truncated_from": truncated_from,
        }

    kinds = _column_kinds(rows, col_names)
    date_cols = [c for c in col_names if kinds[c] == "date"]
    numeric_cols = [c for c in col_names if kinds[c] == "numeric"]
    category_cols = [c for c in col_names if kinds[c] == "category"]

    # Rule 1 — date-x → line
    if len(date_cols) == 1 and numeric_cols:
        return {
            "type": "line",
            "title": title or "Trend",
            "description": description,
            "x_field": date_cols[0],
            "y_fields": numeric_cols[:5],
            "data": data,
            "inferred_from": "date-x → line",
            "truncated_from": truncated_from,
        }

    # Rule 2 — pie when shape looks like share-of-total
    if (
        len(category_cols) == 1
        and len(numeric_cols) == 1
        and 2 <= len(data) <= 6
    ):
        # Decide if it's plausibly a share: all values >= 0 and pie makes
        # visual sense. We're not enforcing sum-to-100; the UI lets the
        # user toggle anyway.
        try:
            vals = [float(r.get(numeric_cols[0]) or 0) for r in data]
            if all(v >= 0 for v in vals) and sum(vals) > 0:
                return {
                    "type": "pie",
                    "title": title or "Distribution",
                    "description": description,
                    "x_field": category_cols[0],
                    "y_fields": [numeric_cols[0]],
                    "data": data,
                    "inferred_from": "1 cat + 1 num + small N → pie",
                    "truncated_from": truncated_from,
                }
        except (TypeError, ValueError):
            pass

    # Rule 3 — bar (categorical x with numeric y, modest N)
    if category_cols and numeric_cols and len(data) <= 30:
        return {
            "type": "bar",
            "title": title or "Comparison",
            "description": description,
            "x_field": category_cols[0],
            "y_fields": numeric_cols[:5],
            "data": data,
            "inferred_from": "1 cat + N num → bar",
            "truncated_from": truncated_from,
        }

    # Numeric-only or numeric-x is uncommon but rendering a bar with row
    # index would be misleading; fall through to table.
    return {
        "type": "table",
        "title": title or "Rows",
        "description": description,
        "x_field": col_names[0],
        "y_fields": col_names[1:] if len(col_names) > 1 else [],
        "data": data,
        "inferred_from": "fallback → table",
        "truncated_from": truncated_from,
    }


def make_visualization(
    rows: Sequence[Dict[str, Any]],
    col_names: Sequence[str],
    *,
    title: str = "",
    description: Optional[str] = None,
    forced_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Public wrapper that allows callers to override the inferred type.

    ``forced_type`` is sanitized against ``CHART_TYPES``; an invalid value is
    ignored and the heuristic decides.
    """
    spec = infer_chart(rows, col_names, title=title, description=description)
    if forced_type and forced_type in CHART_TYPES:
        spec["type"] = forced_type
        spec["inferred_from"] = f"forced={forced_type}"
    return spec
