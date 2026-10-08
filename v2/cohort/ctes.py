"""Reusable building-block CTE fragments, composed from a :class:`CohortConfig`.

Each function returns a single named CTE string with **no leading comma**, so
they can be joined with :func:`cohort.sqlutil.with_clause`. Dependencies between
CTEs are documented on each builder; the canonical order is::

    hypo_diag, tsh_concepts, t4_first, t3_first, excluded_persons, base_cohort

Symptom-cohort CTEs (``ehr_symptom_cohort`` / ``survey_symptom_cohort``) build on
``base_cohort`` and their respective symptom-concept CTEs.
"""

from __future__ import annotations

from .config import (
    CohortConfig,
    EXCL_CENTRAL_ICD10,
    EXCL_CENTRAL_ICD9,
    EXCL_MALABSORPTION_ICD10,
    EXCL_MALABSORPTION_ICD9,
    EXCL_PREGNANCY_ICD10,
    EXCL_PREGNANCY_ICD9,
    EXCL_THYROID_CANCER_ICD10,
    EXCL_THYROID_CANCER_ICD9,
    HYPO_ICD9,
    HYPO_ICD10,
    HYPO_SYMPTOMS,
    PPI_ABSENT_ANSWER_KEYWORDS,
    PPI_SYMPTOM_KEYWORDS,
)
from .sqlutil import concept_id_cte, id_list, quoted_list


# ---------------------------------------------------------------------------
# Diagnosis, labs, drug exposure
# ---------------------------------------------------------------------------

def hypo_diag_cte(cfg: CohortConfig) -> str:
    """``hypo_diag``: persons with >= ``min_dx_count`` hypothyroid diagnoses.

    Matched by OR of two paths: standard SNOMED descendant, or ICD source code.
    Emits ``person_id`` and ``first_dx_date`` (earliest qualifying diagnosis).
    """
    return f"""hypo_diag AS (
    SELECT co.person_id, MIN(co.condition_start_date) AS first_dx_date
    FROM `{cfg.dataset}.condition_occurrence` co
    WHERE
        co.condition_concept_id IN (
            SELECT descendant_concept_id
            FROM `{cfg.dataset}.concept_ancestor`
            WHERE ancestor_concept_id IN ({id_list(cfg.hypo_root_concept_ids)})
        )
        OR co.condition_source_concept_id IN (
            SELECT concept_id FROM `{cfg.dataset}.concept`
            WHERE (vocabulary_id = 'ICD10CM' AND concept_code IN ({quoted_list(HYPO_ICD10)}))
               OR (vocabulary_id = 'ICD9CM'  AND concept_code IN ({quoted_list(HYPO_ICD9)}))
        )
    GROUP BY co.person_id
    HAVING COUNT(DISTINCT co.condition_start_date) >= {cfg.min_dx_count}
)"""


def tsh_concepts_cte(cfg: CohortConfig) -> str:
    """``tsh_concepts``: TSH measurement concept IDs (from discovery)."""
    return concept_id_cte("tsh_concepts", cfg.tsh_concept_ids)


def t4_first_cte(cfg: CohortConfig) -> str:
    """``t4_first``: first levothyroxine (T4) exposure date per person."""
    return f"""t4_first AS (
    SELECT de.person_id, MIN(de.drug_exposure_start_date) AS first_t4_date
    FROM `{cfg.dataset}.drug_exposure` de
    WHERE de.drug_concept_id IN (
        SELECT DISTINCT cd.concept_id
        FROM `{cfg.dataset}.concept_ancestor` ca
        JOIN `{cfg.dataset}.concept` cd ON cd.concept_id = ca.descendant_concept_id
        WHERE ca.ancestor_concept_id = {cfg.t4_ingredient_id}
          AND cd.domain_id = 'Drug'
          AND cd.standard_concept = 'S'
    )
    GROUP BY de.person_id
)"""


def t3_first_cte(cfg: CohortConfig) -> str:
    """``t3_first``: first liothyronine (T3) exposure date per person."""
    return f"""t3_first AS (
    SELECT de.person_id, MIN(de.drug_exposure_start_date) AS first_t3_date
    FROM `{cfg.dataset}.drug_exposure` de
    WHERE de.drug_concept_id IN (
        SELECT DISTINCT cd.concept_id
        FROM `{cfg.dataset}.concept_ancestor` ca
        JOIN `{cfg.dataset}.concept` cd ON cd.concept_id = ca.descendant_concept_id
        WHERE ca.ancestor_concept_id = {cfg.t3_ingredient_id}
          AND cd.domain_id = 'Drug'
          AND cd.standard_concept = 'S'
    )
    GROUP BY de.person_id
)"""


# ---------------------------------------------------------------------------
# Exclusions
# ---------------------------------------------------------------------------

def _icd_match(cfg: CohortConfig, icd10: list[str], icd9: list[str]) -> str:
    """A subquery of concept IDs matching the given ICD-10 / ICD-9 source codes."""
    return f"""SELECT concept_id FROM `{cfg.dataset}.concept`
            WHERE (vocabulary_id = 'ICD10CM' AND concept_code IN ({quoted_list(icd10)}))
               OR (vocabulary_id = 'ICD9CM'  AND concept_code IN ({quoted_list(icd9)}))"""


def _drug_descendants(cfg: CohortConfig, ingredient_ids: list[int]) -> str:
    """A subquery of standard drug concept IDs under the given ingredients."""
    return f"""SELECT DISTINCT cd.concept_id
            FROM `{cfg.dataset}.concept_ancestor` ca
            JOIN `{cfg.dataset}.concept` cd ON cd.concept_id = ca.descendant_concept_id
            WHERE ca.ancestor_concept_id IN ({id_list(ingredient_ids)})
              AND cd.domain_id = 'Drug' AND cd.standard_concept = 'S'"""


def exclusions_cte(cfg: CohortConfig) -> str:
    """``excluded_persons``: persons to drop as confounded (mimics of non-response).

    Depends on ``t4_first`` (pregnancy is windowed around treatment). Structural
    conditions are matched "ever"; pregnancy within the treatment window. Drug
    exclusions are appended only when ``cfg.enable_drug_exclusions`` is set.
    """
    structural_icd10 = (
        EXCL_MALABSORPTION_ICD10 + EXCL_CENTRAL_ICD10 + EXCL_THYROID_CANCER_ICD10
    )
    structural_icd9 = (
        EXCL_MALABSORPTION_ICD9 + EXCL_CENTRAL_ICD9 + EXCL_THYROID_CANCER_ICD9
    )

    blocks = [
        f"""    -- Structural confounders (celiac/IBD/post-GI-surgery malabsorption,
    -- central hypothyroidism, thyroid cancer): matched by ICD source code, ever.
    SELECT DISTINCT co.person_id
    FROM `{cfg.dataset}.condition_occurrence` co
    WHERE co.condition_source_concept_id IN (
        {_icd_match(cfg, structural_icd10, structural_icd9)}
    )""",
        f"""    -- Pregnancy / puerperium within the treatment-response window.
    SELECT DISTINCT co.person_id
    FROM `{cfg.dataset}.condition_occurrence` co
    JOIN t4_first t4 ON co.person_id = t4.person_id
    WHERE co.condition_source_concept_id IN (
        {_icd_match(cfg, EXCL_PREGNANCY_ICD10, EXCL_PREGNANCY_ICD9)}
    )
      AND co.condition_start_date >= DATE_SUB(t4.first_t4_date, INTERVAL {cfg.pre_tsh_lookback_days} DAY)
      AND co.condition_start_date <= DATE_ADD(t4.first_t4_date, INTERVAL {cfg.classify_post_max_days} DAY)""",
    ]

    if cfg.enable_drug_exclusions:
        drug_ids = (
            cfg.interfering_drug_ids
            + cfg.disrupting_drug_ids
            + cfg.desiccated_ingredient_ids
        )
        blocks.append(
            f"""    -- OPTIONAL: interfering / thyroid-disrupting / desiccated-thyroid drugs.
    SELECT DISTINCT de.person_id
    FROM `{cfg.dataset}.drug_exposure` de
    WHERE de.drug_concept_id IN (
        {_drug_descendants(cfg, drug_ids)}
    )"""
        )

    body = "\n    UNION DISTINCT\n".join(blocks)
    return f"excluded_persons AS (\n{body}\n)"


# ---------------------------------------------------------------------------
# Base cohort
# ---------------------------------------------------------------------------

def base_cohort_cte(cfg: CohortConfig) -> str:
    """``base_cohort``: the fully-filtered denominator for every downstream query.

    Depends on ``hypo_diag``, ``t4_first``, ``t3_first``, ``tsh_concepts``,
    ``excluded_persons``. Emits ``person_id``, ``first_dx_date``, ``first_t4_date``.

    Inclusion: >=2 hypothyroid dx; adult at first T4; T4 started within the
    eligibility window after (not before) diagnosis; an elevated pre-treatment
    TSH confirming disease; at least one on-treatment TSH available at steady
    state; T3 not co-started; not an excluded person.
    """
    return f"""base_cohort AS (
    SELECT hd.person_id, hd.first_dx_date, t4.first_t4_date
    FROM hypo_diag hd
    JOIN t4_first t4 ON hd.person_id = t4.person_id
    JOIN `{cfg.dataset}.person` p ON p.person_id = hd.person_id
    WHERE
        -- T4 starts within [dx, dx + window], never before diagnosis
        t4.first_t4_date >= hd.first_dx_date
        AND t4.first_t4_date <= DATE_ADD(hd.first_dx_date, INTERVAL {cfg.t4_window_days} DAY)
        -- adult at treatment start
        AND DATE_DIFF(t4.first_t4_date, DATE(p.birth_datetime), YEAR) >= {cfg.min_age_at_t4}
        -- elevated pre-treatment TSH confirming genuine hypothyroidism
        AND EXISTS (
            SELECT 1 FROM `{cfg.dataset}.measurement` m
            JOIN tsh_concepts tc ON m.measurement_concept_id = tc.concept_id
            WHERE m.person_id = hd.person_id
              AND m.value_as_number > {cfg.pre_tsh_elevated}
              AND m.measurement_date >= DATE_SUB(hd.first_dx_date, INTERVAL {cfg.pre_tsh_lookback_days} DAY)
              AND m.measurement_date <= hd.first_dx_date
        )
        -- at least one on-treatment TSH available at steady state (3-6 mo)
        AND EXISTS (
            SELECT 1 FROM `{cfg.dataset}.measurement` m
            JOIN tsh_concepts tc ON m.measurement_concept_id = tc.concept_id
            WHERE m.person_id = hd.person_id
              AND m.value_as_number IS NOT NULL
              AND m.measurement_date >= DATE_ADD(t4.first_t4_date, INTERVAL {cfg.post_tsh_min_days} DAY)
              AND m.measurement_date <= DATE_ADD(t4.first_t4_date, INTERVAL {cfg.post_tsh_avail_max_days} DAY)
        )
        -- T3 not co-started within the exclusion window of T4
        AND NOT EXISTS (
            SELECT 1 FROM t3_first t3
            WHERE t3.person_id = hd.person_id
              AND t3.first_t3_date <= DATE_ADD(t4.first_t4_date, INTERVAL {cfg.t3_coexclusion_days} DAY)
        )
        -- not confounded by an excluded condition/drug
        AND hd.person_id NOT IN (SELECT person_id FROM excluded_persons)
)"""


def base_cohort_ctes(cfg: CohortConfig) -> list[str]:
    """The ordered list of CTEs required to define ``base_cohort``."""
    return [
        hypo_diag_cte(cfg),
        tsh_concepts_cte(cfg),
        t4_first_cte(cfg),
        t3_first_cte(cfg),
        exclusions_cte(cfg),
        base_cohort_cte(cfg),
    ]


# ---------------------------------------------------------------------------
# Symptom concept maps
# ---------------------------------------------------------------------------

def hypo_symptom_concepts_cte(cfg: CohortConfig) -> str:
    """``hypo_symptom_concepts``: ICD-10 symptom codes -> (concept_id, category)."""
    rows = [
        f"SELECT '{cat}' AS symptom_category, '{code}' AS code"
        for cat, codes in HYPO_SYMPTOMS.items()
        for code in codes
    ]
    mapping = "\n        UNION ALL ".join(rows)
    return f"""hypo_symptom_concepts AS (
    SELECT c.concept_id, m.symptom_category
    FROM `{cfg.dataset}.concept` c
    JOIN (
        {mapping}
    ) m ON c.concept_code = m.code AND c.vocabulary_id = 'ICD10CM'
)"""


def ppi_symptom_concepts_cte(cfg: CohortConfig) -> str:
    """``ppi_symptom_concepts``: PPI-survey observation concepts -> category.

    Matched by keyword patterns on the observation concept name.
    """
    blocks = []
    for cat, patterns in PPI_SYMPTOM_KEYWORDS.items():
        like = " OR ".join(f"LOWER(concept_name) LIKE '{p}'" for p in patterns)
        blocks.append(
            f"""        SELECT concept_id, '{cat}' AS symptom_category
        FROM `{cfg.dataset}.concept`
        WHERE domain_id = 'Observation' AND ({like})"""
        )
    union = "\n        UNION ALL\n".join(blocks)
    return f"""ppi_symptom_concepts AS (
{union}
)"""


def ppi_absent_answer_concepts_cte(cfg: CohortConfig) -> str:
    """``ppi_absent_answer_concepts``: PPI answer concepts meaning "symptom gone".

    PPI survey answers are coded in ``observation.value_as_concept_id``; this set
    identifies the answer concepts that affirm the symptom is absent/resolved
    (e.g. "Not at all"), so a post-treatment answer can positively confirm
    resolution. Matched by keyword on the answer concept name -- review the result.
    Degrades to the empty set (no confirmed-resolution class) if nothing matches.
    """
    like = " OR ".join(
        f"LOWER(concept_name) LIKE '{p}'" for p in PPI_ABSENT_ANSWER_KEYWORDS
    )
    return f"""ppi_absent_answer_concepts AS (
    SELECT concept_id
    FROM `{cfg.dataset}.concept`
    WHERE vocabulary_id = 'PPI' AND concept_class_id = 'Answer'
      AND ({like})
)"""


def ehr_symptom_cohort_cte(cfg: CohortConfig) -> str:
    """``ehr_symptom_cohort``: base cohort + >=1 target symptom in EHR pre-dx.

    Depends on ``base_cohort`` and ``hypo_symptom_concepts``.
    """
    return f"""ehr_symptom_cohort AS (
    SELECT bc.person_id, bc.first_dx_date, bc.first_t4_date
    FROM base_cohort bc
    WHERE bc.person_id IN (
        SELECT DISTINCT co.person_id
        FROM `{cfg.dataset}.condition_occurrence` co
        JOIN base_cohort bc2 ON co.person_id = bc2.person_id
        JOIN hypo_symptom_concepts sc ON co.condition_source_concept_id = sc.concept_id
        WHERE co.condition_start_date >= DATE_SUB(bc2.first_dx_date, INTERVAL {cfg.symptom_lookback_days} DAY)
          AND co.condition_start_date <= bc2.first_dx_date
    )
)"""


def survey_symptom_cohort_cte(cfg: CohortConfig) -> str:
    """``survey_symptom_cohort``: base cohort + >=1 target symptom in PPI pre-dx.

    Depends on ``base_cohort`` and ``ppi_symptom_concepts``.
    """
    return f"""survey_symptom_cohort AS (
    SELECT bc.person_id, bc.first_dx_date, bc.first_t4_date
    FROM base_cohort bc
    WHERE bc.person_id IN (
        SELECT DISTINCT o.person_id
        FROM `{cfg.dataset}.observation` o
        JOIN base_cohort bc2 ON o.person_id = bc2.person_id
        JOIN ppi_symptom_concepts psc ON o.observation_concept_id = psc.concept_id
        WHERE o.observation_date >= DATE_SUB(bc2.first_dx_date, INTERVAL {cfg.symptom_lookback_days} DAY)
          AND o.observation_date <= bc2.first_dx_date
    )
)"""
