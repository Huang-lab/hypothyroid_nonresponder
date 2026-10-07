"""Hypothyroidism T4 non-responder cohort builder (All of Us / OMOP CDM).

Typical use inside the workbench notebook::

    from cohort import CohortConfig, Runner, concepts, queries

    runner = Runner()
    cfg = CohortConfig(dataset=runner.dataset)
    concepts.resolve(runner, cfg)          # discover concept IDs from the vocab
    df = runner.df(queries.base_cohort_query(cfg))
"""

from __future__ import annotations

from . import concepts, ctes, queries
from .config import CohortConfig
from .runner import Runner

__all__ = ["CohortConfig", "Runner", "concepts", "ctes", "queries"]
