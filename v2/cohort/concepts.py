"""Data-driven concept-ID discovery from the CDR vocabulary.

Concept IDs are resolved from ``concept`` / ``concept_ancestor`` at runtime and
written back onto a :class:`~cohort.config.CohortConfig`. Each discovery helper
returns the review DataFrame it queried so the notebook can display and confirm
the selection before the IDs are used downstream (per project convention).
"""

from __future__ import annotations

import pandas as pd

from .config import (
    CohortConfig,
    DESICCATED_THYROID_NAME,
    INTERFERING_DRUG_NAMES,
    LAB_NAME_PATTERNS,
    THYROID_DISRUPTING_DRUG_NAMES,
    TSH_LOINC_CODES,
)
from .runner import Runner
from .sqlutil import quoted_list


def discover_hypo_roots(runner: Runner, cfg: CohortConfig) -> pd.DataFrame:
    """Find SNOMED standard root concepts for hypothyroidism / Hashimoto's.

    Sets ``cfg.hypo_root_concept_ids`` and returns the matched concepts.
    """
    sql = f"""
    SELECT concept_id, concept_name, concept_code AS snomed_code,
           standard_concept, domain_id, concept_class_id
    FROM `{cfg.dataset}.concept`
    WHERE vocabulary_id = 'SNOMED'
      AND standard_concept = 'S'
      AND domain_id = 'Condition'
      AND (LOWER(concept_name) = 'hypothyroidism'
           OR LOWER(concept_name) LIKE 'hashi%thyroiditis%')
    ORDER BY concept_name
    """
    df = runner.df(sql)
    cfg.hypo_root_concept_ids = [int(i) for i in df["concept_id"].tolist()]
    return df


def discover_ingredient(runner: Runner, cfg: CohortConfig, name: str) -> int | None:
    """Resolve a single RxNorm standard ingredient concept ID by exact name."""
    sql = f"""
    SELECT c.concept_id
    FROM `{cfg.dataset}.concept` c
    WHERE LOWER(c.concept_name) = '{name.lower()}'
      AND c.vocabulary_id = 'RxNorm'
      AND c.concept_class_id = 'Ingredient'
      AND c.standard_concept = 'S'
    """
    df = runner.df(sql)
    return int(df.iloc[0, 0]) if len(df) else None


def discover_ingredients(
    runner: Runner, cfg: CohortConfig, names: list[str]
) -> list[int]:
    """Resolve RxNorm ingredient IDs for a list of names (missing ones dropped)."""
    lowered = quoted_list([n.lower() for n in names])
    sql = f"""
    SELECT c.concept_id, c.concept_name
    FROM `{cfg.dataset}.concept` c
    WHERE LOWER(c.concept_name) IN ({lowered})
      AND c.vocabulary_id = 'RxNorm'
      AND c.concept_class_id = 'Ingredient'
      AND c.standard_concept = 'S'
    """
    df = runner.df(sql)
    return [int(i) for i in df["concept_id"].tolist()]


def discover_tsh_concepts(runner: Runner, cfg: CohortConfig) -> pd.DataFrame:
    """Resolve TSH measurement concepts via known LOINC codes.

    Sets ``cfg.tsh_concept_ids`` and returns the matched concepts.
    """
    sql = f"""
    SELECT concept_id, concept_name, concept_code AS loinc_code, standard_concept
    FROM `{cfg.dataset}.concept`
    WHERE vocabulary_id = 'LOINC'
      AND concept_code IN ({quoted_list(TSH_LOINC_CODES)})
    ORDER BY concept_code
    """
    df = runner.df(sql)
    cfg.tsh_concept_ids = [int(i) for i in df["concept_id"].tolist()]
    return df


def discover_lab_panel(runner: Runner, cfg: CohortConfig) -> pd.DataFrame:
    """Resolve the full thyroid lab panel by LOINC concept-name patterns.

    Sets ``cfg.lab_concept_ids`` (analyte -> [concept_id]) and returns one row
    per matched concept, tagged with its analyte, for review.
    """
    frames = []
    for analyte, patterns in LAB_NAME_PATTERNS.items():
        like = " OR ".join(f"LOWER(concept_name) LIKE '{p}'" for p in patterns)
        sql = f"""
        SELECT concept_id, concept_name, concept_code AS loinc_code
        FROM `{cfg.dataset}.concept`
        WHERE vocabulary_id = 'LOINC'
          AND domain_id = 'Measurement'
          AND standard_concept = 'S'
          AND ({like})
        """
        df = runner.df(sql)
        df.insert(0, "analyte", analyte)
        frames.append(df)
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    cfg.lab_concept_ids = {
        analyte: [int(i) for i in out.loc[out["analyte"] == analyte, "concept_id"]]
        for analyte in LAB_NAME_PATTERNS
    }
    return out


def resolve(runner: Runner, cfg: CohortConfig) -> CohortConfig:
    """Populate every discovered-ID field on ``cfg`` in one call.

    Drug-exclusion ingredients are only resolved when
    ``cfg.enable_drug_exclusions`` is set.
    """
    discover_hypo_roots(runner, cfg)
    cfg.t4_ingredient_id = discover_ingredient(runner, cfg, "levothyroxine")
    cfg.t3_ingredient_id = discover_ingredient(runner, cfg, "liothyronine")
    discover_tsh_concepts(runner, cfg)
    discover_lab_panel(runner, cfg)
    if cfg.enable_drug_exclusions:
        cfg.interfering_drug_ids = discover_ingredients(
            runner, cfg, INTERFERING_DRUG_NAMES
        )
        cfg.disrupting_drug_ids = discover_ingredients(
            runner, cfg, THYROID_DISRUPTING_DRUG_NAMES
        )
        cfg.desiccated_ingredient_ids = discover_ingredients(
            runner, cfg, [DESICCATED_THYROID_NAME]
        )
    return cfg
