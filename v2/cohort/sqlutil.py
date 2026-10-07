"""Tiny SQL string-formatting helpers shared by the CTE and query builders."""

from __future__ import annotations

from typing import Iterable


def id_list(ids: Iterable[int]) -> str:
    """Render integer concept IDs as a SQL ``IN`` list body: ``1, 2, 3``.

    Returns ``NULL`` for an empty iterable so ``IN (NULL)`` matches nothing
    rather than producing a syntax error.
    """
    ids = [int(i) for i in ids]
    return ", ".join(str(i) for i in ids) if ids else "NULL"


def quoted_list(codes: Iterable[str]) -> str:
    """Render string codes as a SQL ``IN`` list body: ``'E00', 'E01'``."""
    codes = list(codes)
    return ", ".join(f"'{c}'" for c in codes) if codes else "NULL"


def with_clause(ctes: Iterable[str]) -> str:
    """Join named CTE fragments (each without a leading comma) into a WITH body."""
    parts = [c.strip() for c in ctes if c and c.strip()]
    return "WITH " + ",\n".join(parts)


def concept_id_cte(name: str, ids: Iterable[int]) -> str:
    """Build a one-column CTE of literal concept IDs, safe for an empty list."""
    ids = [int(i) for i in ids]
    if not ids:
        return f"{name} AS (SELECT CAST(NULL AS INT64) AS concept_id WHERE FALSE)"
    body = ", ".join(str(i) for i in ids)
    return f"{name} AS (SELECT concept_id FROM UNNEST([{body}]) AS concept_id)"
