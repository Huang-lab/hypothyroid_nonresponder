"""Assembled, runnable queries composed from the building-block CTEs.

Every query is built from :mod:`cohort.ctes`, so a change to a cohort definition
propagates everywhere. Each builder returns a SQL string; execute it with
``Runner.df``.
"""

from __future__ import annotations

from . import ctes
from .config import CohortConfig
from .sqlutil import id_list, with_clause


# ---------------------------------------------------------------------------
# Cohort member lists
# ---------------------------------------------------------------------------


def base_cohort_query(cfg: CohortConfig) -> str:
    """Members of the base cohort with diagnosis/treatment dates."""
    sql = with_clause(ctes.base_cohort_ctes(cfg))
    return (
        sql
        + """
SELECT bc.person_id, bc.first_dx_date, bc.first_t4_date,
       DATE_DIFF(bc.first_t4_date, bc.first_dx_date, DAY) AS days_dx_to_t4
FROM base_cohort bc
ORDER BY bc.person_id
"""
    )


def ehr_symptom_cohort_query(cfg: CohortConfig) -> str:
    """Members of the EHR symptom cohort."""
    cte_list = ctes.base_cohort_ctes(cfg) + [
        ctes.hypo_symptom_concepts_cte(cfg),
        ctes.ehr_symptom_cohort_cte(cfg),
    ]
    sql = with_clause(cte_list)
    return (
        sql
        + """
SELECT sc.person_id, sc.first_dx_date, sc.first_t4_date,
       DATE_DIFF(sc.first_t4_date, sc.first_dx_date, DAY) AS days_dx_to_t4
FROM ehr_symptom_cohort sc
ORDER BY sc.person_id
"""
    )


def survey_symptom_cohort_query(cfg: CohortConfig) -> str:
    """Members of the PPI survey symptom cohort."""
    cte_list = ctes.base_cohort_ctes(cfg) + [
        ctes.ppi_symptom_concepts_cte(cfg),
        ctes.survey_symptom_cohort_cte(cfg),
    ]
    sql = with_clause(cte_list)
    return (
        sql
        + """
SELECT sc.person_id, sc.first_dx_date, sc.first_t4_date,
       DATE_DIFF(sc.first_t4_date, sc.first_dx_date, DAY) AS days_dx_to_t4
FROM survey_symptom_cohort sc
ORDER BY sc.person_id
"""
    )


# ---------------------------------------------------------------------------
# TSH-based response classification (non-responder / responder / partial)
# ---------------------------------------------------------------------------


def _tsh_classification_sql(
    cfg: CohortConfig, cohort_name: str, cohort_ctes: list[str]
) -> str:
    """Classify each cohort member by pre- vs. sustained on-treatment TSH.

    non_responder: >= ``min_post_measurements`` on-treatment TSH, none normalized,
    and >= ``min_post_measurements`` elevated (never normalized despite follow-up).
    responder: >= ``min_post_measurements`` normalized on-treatment TSH.
    Otherwise partial (some data) or insufficient_data (no on-treatment TSH).
    """
    classification = with_clause(
        cohort_ctes
        + [
            f"""pre_tsh AS (
    SELECT m.person_id, AVG(m.value_as_number) AS avg_pre_tsh, COUNT(*) AS n_pre
    FROM `{cfg.dataset}.measurement` m
    JOIN {cohort_name} ch ON m.person_id = ch.person_id
    JOIN tsh_concepts tc ON m.measurement_concept_id = tc.concept_id
    WHERE m.value_as_number IS NOT NULL
      AND m.measurement_date >= DATE_SUB(ch.first_dx_date, INTERVAL {cfg.pre_tsh_lookback_days} DAY)
      AND m.measurement_date <= ch.first_dx_date
    GROUP BY m.person_id
)""",
            f"""post_tsh AS (
    SELECT m.person_id,
        COUNT(*) AS n_post,
        COUNTIF(m.value_as_number > {cfg.tsh_elevated}) AS n_elevated,
        COUNTIF(m.value_as_number BETWEEN {cfg.tsh_normal_low} AND {cfg.tsh_normal_high}) AS n_normal,
        AVG(m.value_as_number) AS avg_post_tsh
    FROM `{cfg.dataset}.measurement` m
    JOIN {cohort_name} ch ON m.person_id = ch.person_id
    JOIN tsh_concepts tc ON m.measurement_concept_id = tc.concept_id
    WHERE m.value_as_number IS NOT NULL
      AND m.measurement_date >= DATE_ADD(ch.first_t4_date, INTERVAL {cfg.post_tsh_min_days} DAY)
      AND m.measurement_date <= DATE_ADD(ch.first_t4_date, INTERVAL {cfg.classify_post_max_days} DAY)
    GROUP BY m.person_id
)""",
        ]
    )
    return (
        classification
        + f"""
SELECT
    ch.person_id, ch.first_dx_date, ch.first_t4_date,
    pre.avg_pre_tsh,
    COALESCE(post.n_post, 0)     AS n_post_tsh,
    COALESCE(post.n_elevated, 0) AS n_elevated,
    COALESCE(post.n_normal, 0)   AS n_normal,
    post.avg_post_tsh,
    CASE
        WHEN COALESCE(post.n_post, 0) >= {cfg.min_post_measurements}
             AND COALESCE(post.n_normal, 0) = 0
             AND COALESCE(post.n_elevated, 0) >= {cfg.min_post_measurements}
            THEN 'non_responder'
        WHEN COALESCE(post.n_normal, 0) >= {cfg.min_post_measurements}
            THEN 'responder'
        WHEN COALESCE(post.n_post, 0) >= 1
            THEN 'partial'
        ELSE 'insufficient_data'
    END AS response_class
FROM {cohort_name} ch
LEFT JOIN pre_tsh  pre  ON ch.person_id = pre.person_id
LEFT JOIN post_tsh post ON ch.person_id = post.person_id
ORDER BY ch.person_id
"""
    )


def base_tsh_classification_query(cfg: CohortConfig) -> str:
    """TSH response classification for the base cohort."""
    return _tsh_classification_sql(cfg, "base_cohort", ctes.base_cohort_ctes(cfg))


def ehr_tsh_classification_query(cfg: CohortConfig) -> str:
    """TSH response classification for the EHR symptom cohort."""
    cte_list = ctes.base_cohort_ctes(cfg) + [
        ctes.hypo_symptom_concepts_cte(cfg),
        ctes.ehr_symptom_cohort_cte(cfg),
    ]
    return _tsh_classification_sql(cfg, "ehr_symptom_cohort", cte_list)


def survey_tsh_classification_query(cfg: CohortConfig) -> str:
    """TSH response classification for the survey symptom cohort."""
    cte_list = ctes.base_cohort_ctes(cfg) + [
        ctes.ppi_symptom_concepts_cte(cfg),
        ctes.survey_symptom_cohort_cte(cfg),
    ]
    return _tsh_classification_sql(cfg, "survey_symptom_cohort", cte_list)


# ---------------------------------------------------------------------------
# T3 add-on non-responder (liothyronine started after the co-start window)
# ---------------------------------------------------------------------------


def _t3_nonresponder_sql(
    cfg: CohortConfig, cohort_name: str, cohort_ctes: list[str]
) -> str:
    sql = with_clause(cohort_ctes)
    return (
        sql
        + f"""
SELECT ch.person_id, ch.first_dx_date, ch.first_t4_date,
       t3.first_t3_date,
       DATE_DIFF(t3.first_t3_date, ch.first_t4_date, DAY) AS days_t4_to_t3,
       TRUE AS t3_nonresponder
FROM {cohort_name} ch
JOIN t3_first t3 ON ch.person_id = t3.person_id
WHERE t3.first_t3_date >  DATE_ADD(ch.first_t4_date, INTERVAL {cfg.t3_coexclusion_days} DAY)
  AND t3.first_t3_date <= DATE_ADD(ch.first_t4_date, INTERVAL {cfg.t3_nonresponder_window_days} DAY)
ORDER BY ch.person_id
"""
    )


def base_t3_nonresponder_query(cfg: CohortConfig) -> str:
    """T3 add-on non-responders in the base cohort."""
    return _t3_nonresponder_sql(cfg, "base_cohort", ctes.base_cohort_ctes(cfg))


def ehr_t3_nonresponder_query(cfg: CohortConfig) -> str:
    """T3 add-on non-responders in the EHR symptom cohort."""
    cte_list = ctes.base_cohort_ctes(cfg) + [
        ctes.hypo_symptom_concepts_cte(cfg),
        ctes.ehr_symptom_cohort_cte(cfg),
    ]
    return _t3_nonresponder_sql(cfg, "ehr_symptom_cohort", cte_list)


def survey_t3_nonresponder_query(cfg: CohortConfig) -> str:
    """T3 add-on non-responders in the survey symptom cohort."""
    cte_list = ctes.base_cohort_ctes(cfg) + [
        ctes.ppi_symptom_concepts_cte(cfg),
        ctes.survey_symptom_cohort_cte(cfg),
    ]
    return _t3_nonresponder_sql(cfg, "survey_symptom_cohort", cte_list)


# ---------------------------------------------------------------------------
# Symptom-persistence response classification (same symptom before vs. after T4)
#
# A member's pre-T4 symptom categories are compared against the post-T4 window:
#   symptom_nonresponder: >= 1 pre-T4 symptom category reappears post-T4 (persists)
#   symptom_responder:    had >= 1 pre-T4 symptom category, none reappear post-T4
#   no_pre_symptom:       no target symptom in the pre-T4 window (cannot classify)
#
# The survey (PPI) path adds a stronger, positively-confirmed class by reading the
# survey *answer value* (observation.value_as_concept_id), not just the presence of
# a question record:
#   symptom_responder_confirmed: a post-T4 survey answer affirms the symptom is GONE
#                                (e.g. "Not at all"), and none persists.
# A "gone" answer is also removed from the persistence set, so answering "Not at all"
# post-T4 no longer counts as the symptom persisting.
#
# Caveat: for the EHR path (and the plain symptom_responder class) an "absent" post-T4
# symptom may reflect the lack of a coded encounter rather than true resolution, so it
# is a weaker signal than a measured TSH normalization or a confirmed survey denial.
# Treat it as supportive, not definitive.
# ---------------------------------------------------------------------------

# Presence-based CASE (EHR): persistence vs. inferred resolution vs. no pre-symptom.
_EHR_SYMPTOM_CLASS_CASE = """CASE
        WHEN COALESCE(ss.n_persist_categories, 0) >= 1 THEN 'symptom_nonresponder'
        WHEN COALESCE(ss.n_pre_categories, 0) >= 1 THEN 'symptom_responder'
        ELSE 'no_pre_symptom'
    END"""

# Answer-aware CASE (survey): persistence, confirmed resolution (positive "gone"
# answer), inferred resolution (no post-T4 record), or no pre-symptom.
_SURVEY_SYMPTOM_CLASS_CASE = """CASE
        WHEN COALESCE(ss.n_persist_categories, 0) >= 1 THEN 'symptom_nonresponder'
        WHEN COALESCE(ss.n_resolved_categories, 0) >= 1 THEN 'symptom_responder_confirmed'
        WHEN COALESCE(ss.n_persist_categories, 0) == 0 THEN 'symptom_responder_unconfirmed'
        WHEN COALESCE(ss.n_pre_categories, 0) >= 1 THEN 'symptom_responder'
        ELSE 'no_pre_symptom'
    END"""

_EHR_COUNT_COLS = """       COALESCE(ss.n_pre_categories, 0)     AS n_pre_symptom_categories,
       COALESCE(ss.n_persist_categories, 0) AS n_persistent_symptom_categories,"""

_SURVEY_COUNT_COLS = """       COALESCE(ss.n_pre_categories, 0)      AS n_pre_symptom_categories,
       COALESCE(ss.n_persist_categories, 0)  AS n_persistent_symptom_categories,
       COALESCE(ss.n_resolved_categories, 0) AS n_resolved_symptom_categories,"""


def _ehr_symptom_status_ctes(cfg: CohortConfig) -> list[str]:
    """Pre/post symptom CTEs plus a per-person persistence summary (EHR path).

    ``symptom_status`` has one row per member with >= 1 pre-T4 symptom category;
    ``n_persist_categories`` counts the pre-T4 categories whose condition recurs in
    the post-T4 window. Members with no pre-T4 symptom are absent (LEFT-joined in).
    """
    ds = cfg.dataset
    return [
        f"""pre_symptoms AS (
    SELECT DISTINCT co.person_id, sc.symptom_category
    FROM `{ds}.condition_occurrence` co
    JOIN ehr_symptom_cohort ch ON co.person_id = ch.person_id
    JOIN hypo_symptom_concepts sc ON co.condition_source_concept_id = sc.concept_id
    WHERE co.condition_start_date >= DATE_SUB(ch.first_t4_date, INTERVAL {cfg.symptom_lookback_days} DAY)
      AND co.condition_start_date <  ch.first_t4_date
)""",
        f"""post_symptoms AS (
    SELECT DISTINCT co.person_id, sc.symptom_category
    FROM `{ds}.condition_occurrence` co
    JOIN ehr_symptom_cohort ch ON co.person_id = ch.person_id
    JOIN hypo_symptom_concepts sc ON co.condition_source_concept_id = sc.concept_id
    WHERE co.condition_start_date >= DATE_ADD(ch.first_t4_date, INTERVAL {cfg.symptom_post_min_days} DAY)
      AND co.condition_start_date <= DATE_ADD(ch.first_t4_date, INTERVAL {cfg.symptom_post_max_days} DAY)
)""",
        """symptom_status AS (
    SELECT
        pre.person_id,
        COUNT(DISTINCT pre.symptom_category)  AS n_pre_categories,
        COUNT(DISTINCT post.symptom_category) AS n_persist_categories
    FROM pre_symptoms pre
    LEFT JOIN post_symptoms post
      ON pre.person_id = post.person_id
     AND pre.symptom_category = post.symptom_category
    GROUP BY pre.person_id
)""",
    ]


def _survey_symptom_status_ctes(cfg: CohortConfig) -> list[str]:
    """Answer-aware pre/post symptom CTEs plus a per-person summary (survey path).

    Depends on ``ppi_absent_answer_concepts`` (PPI answer concepts meaning the
    symptom is gone). Post-T4 survey records are split by their answer value:
    ``post_present`` (any non-"gone" answer -> still symptomatic) and
    ``post_absent`` (a positively-"gone" answer -> resolved). ``symptom_status``
    then counts persisting vs. confirmed-resolved pre-T4 categories per member.
    """
    ds = cfg.dataset
    post_window = (
        f"o.observation_date >= DATE_ADD(ch.first_t4_date, INTERVAL {cfg.symptom_post_min_days} DAY)\n"
        f"      AND o.observation_date <= DATE_ADD(ch.first_t4_date, INTERVAL {cfg.symptom_post_max_days} DAY)"
    )
    return [
        f"""pre_symptoms AS (
    SELECT DISTINCT o.person_id, psc.symptom_category
    FROM `{ds}.observation` o
    JOIN survey_symptom_cohort ch ON o.person_id = ch.person_id
    JOIN ppi_symptom_concepts psc ON o.observation_concept_id = psc.concept_id
    WHERE o.observation_date >= DATE_SUB(ch.first_t4_date, INTERVAL {cfg.symptom_lookback_days} DAY)
      AND o.observation_date <  ch.first_t4_date
)""",
        f"""post_present AS (
    -- post-T4 answer that does NOT affirm the symptom is gone (treated as persisting)
    SELECT DISTINCT o.person_id, psc.symptom_category
    FROM `{ds}.observation` o
    JOIN survey_symptom_cohort ch ON o.person_id = ch.person_id
    JOIN ppi_symptom_concepts psc ON o.observation_concept_id = psc.concept_id
    WHERE {post_window}
      AND COALESCE(o.value_as_concept_id, 0) NOT IN (
          SELECT concept_id FROM ppi_absent_answer_concepts
      )
)""",
        f"""post_absent AS (
    -- post-T4 answer that affirms the symptom is gone (confirmed resolution)
    SELECT DISTINCT o.person_id, psc.symptom_category
    FROM `{ds}.observation` o
    JOIN survey_symptom_cohort ch ON o.person_id = ch.person_id
    JOIN ppi_symptom_concepts psc ON o.observation_concept_id = psc.concept_id
    WHERE {post_window}
      AND o.value_as_concept_id IN (
          SELECT concept_id FROM ppi_absent_answer_concepts
      )
)""",
        """symptom_status AS (
    SELECT
        pre.person_id,
        COUNT(DISTINCT pre.symptom_category)     AS n_pre_categories,
        COUNT(DISTINCT present.symptom_category) AS n_persist_categories,
        COUNT(DISTINCT absent.symptom_category)  AS n_resolved_categories
    FROM pre_symptoms pre
    LEFT JOIN post_present present
      ON pre.person_id = present.person_id AND pre.symptom_category = present.symptom_category
    LEFT JOIN post_absent absent
      ON pre.person_id = absent.person_id AND pre.symptom_category = absent.symptom_category
    GROUP BY pre.person_id
)""",
    ]


def _symptom_classification_sql(
    cohort_name: str,
    cohort_ctes: list[str],
    status_ctes: list[str],
    class_case: str,
    count_cols: str,
    *,
    filter_class: str | None = None,
    flag_name: str | None = None,
) -> str:
    """Classify each cohort member by pre- vs. post-T4 symptom status.

    ``status_ctes`` must end in a ``symptom_status`` CTE (one row per member with a
    pre-T4 symptom) and ``class_case`` is the CASE over it. With no ``filter_class``
    this returns one row per member with a ``symptom_response_class`` column; with
    ``filter_class``/``flag_name`` it returns only that class, with a boolean flag
    column (the backward-compatible shape of the non-responder queries).
    """
    sql = with_clause(cohort_ctes + status_ctes)
    if filter_class is not None:
        return (
            sql
            + f"""
SELECT ch.person_id, ch.first_dx_date, ch.first_t4_date,
       TRUE AS {flag_name}
FROM {cohort_name} ch
LEFT JOIN symptom_status ss ON ch.person_id = ss.person_id
WHERE {class_case} = '{filter_class}'
ORDER BY ch.person_id
"""
        )
    return (
        sql
        + f"""
SELECT ch.person_id, ch.first_dx_date, ch.first_t4_date,
{count_cols}
       {class_case} AS symptom_response_class
FROM {cohort_name} ch
LEFT JOIN symptom_status ss ON ch.person_id = ss.person_id
ORDER BY ch.person_id
"""
    )


def _ehr_symptom_args(cfg: CohortConfig) -> dict:
    """Builder args for the EHR (condition_occurrence / ICD-10) symptom queries."""
    return dict(
        cohort_name="ehr_symptom_cohort",
        cohort_ctes=ctes.base_cohort_ctes(cfg)
        + [ctes.hypo_symptom_concepts_cte(cfg), ctes.ehr_symptom_cohort_cte(cfg)],
        status_ctes=_ehr_symptom_status_ctes(cfg),
        class_case=_EHR_SYMPTOM_CLASS_CASE,
        count_cols=_EHR_COUNT_COLS,
    )


def _survey_symptom_args(cfg: CohortConfig) -> dict:
    """Builder args for the survey (observation / PPI) symptom queries."""
    return dict(
        cohort_name="survey_symptom_cohort",
        cohort_ctes=ctes.base_cohort_ctes(cfg)
        + [
            ctes.ppi_symptom_concepts_cte(cfg),
            ctes.ppi_absent_answer_concepts_cte(cfg),
            ctes.survey_symptom_cohort_cte(cfg),
        ],
        status_ctes=_survey_symptom_status_ctes(cfg),
        class_case=_SURVEY_SYMPTOM_CLASS_CASE,
        count_cols=_SURVEY_COUNT_COLS,
    )


def ehr_symptom_classification_query(cfg: CohortConfig) -> str:
    """Symptom-persistence response class for every EHR symptom cohort member."""
    return _symptom_classification_sql(**_ehr_symptom_args(cfg))


def survey_symptom_classification_query(cfg: CohortConfig) -> str:
    """Symptom response class for every survey symptom cohort member.

    Includes the answer-confirmed ``symptom_responder_confirmed`` class.
    """
    return _symptom_classification_sql(**_survey_symptom_args(cfg))


def ehr_symptom_nonresponder_query(cfg: CohortConfig) -> str:
    """EHR symptom cohort members whose pre-T4 symptom persists post-T4."""
    return _symptom_classification_sql(
        **_ehr_symptom_args(cfg),
        filter_class="symptom_nonresponder",
        flag_name="ehr_symptom_nonresponder",
    )


def ehr_symptom_responder_query(cfg: CohortConfig) -> str:
    """EHR symptom cohort members with pre-T4 symptoms that all resolve post-T4."""
    return _symptom_classification_sql(
        **_ehr_symptom_args(cfg),
        filter_class="symptom_responder",
        flag_name="ehr_symptom_responder",
    )


def survey_symptom_nonresponder_query(cfg: CohortConfig) -> str:
    """Survey symptom cohort members whose pre-T4 symptom domain persists post-T4."""
    return _symptom_classification_sql(
        **_survey_symptom_args(cfg),
        filter_class="symptom_nonresponder",
        flag_name="survey_symptom_nonresponder",
    )


def survey_symptom_responder_query(cfg: CohortConfig) -> str:
    """Survey symptom cohort members with pre-T4 symptoms absent (no record) post-T4.

    Inferred resolution only; for positively-confirmed resolution (a survey answer
    affirming the symptom is gone) use :func:`survey_symptom_responder_confirmed_query`.
    """
    return _symptom_classification_sql(
        **_survey_symptom_args(cfg),
        filter_class="symptom_responder",
        flag_name="survey_symptom_responder",
    )


def survey_symptom_responder_confirmed_query(cfg: CohortConfig) -> str:
    """Survey symptom cohort members with a post-T4 answer affirming the symptom is gone."""
    return _symptom_classification_sql(
        **_survey_symptom_args(cfg),
        filter_class="symptom_responder_confirmed",
        flag_name="survey_symptom_responder_confirmed",
    )


# ---------------------------------------------------------------------------
# Feasibility: lab-data and genomic-data availability over the base cohort
# ---------------------------------------------------------------------------


def lab_availability_query(cfg: CohortConfig) -> str:
    """Count base-cohort members with >= 1 measurement for each thyroid analyte.

    Uses the concept IDs discovered into ``cfg.lab_concept_ids``.
    """
    blocks = []
    for analyte, ids in cfg.lab_concept_ids.items():
        blocks.append(
            f"""    SELECT '{analyte}' AS analyte,
           COUNT(DISTINCT m.person_id) AS n_persons_with_lab
    FROM `{cfg.dataset}.measurement` m
    JOIN base_cohort bc ON m.person_id = bc.person_id
    WHERE m.measurement_concept_id IN ({id_list(ids)})"""
        )
    union = "\n    UNION ALL\n".join(blocks)
    sql = with_clause(ctes.base_cohort_ctes(cfg))
    return sql + "\n" + union + "\nORDER BY n_persons_with_lab DESC\n"


def genomic_availability_query(cfg: CohortConfig) -> str:
    """Feasibility count: base-cohort overlap with WGS / genotyping-array data.

    Reads the All of Us ``cb_search_person`` helper table. This is a data-
    availability check only (it determines whether a genetic analysis is even
    feasible); it is not itself a GWAS criterion.
    """
    sql = with_clause(ctes.base_cohort_ctes(cfg))
    return (
        sql
        + f"""
SELECT
    COUNT(*) AS base_cohort_n,
    COUNTIF(cb.has_whole_genome_variant = 1) AS n_with_wgs,
    COUNTIF(cb.has_array_data = 1)           AS n_with_array,
    COUNTIF(cb.has_whole_genome_variant = 1 OR cb.has_array_data = 1) AS n_with_any_genomic
FROM base_cohort bc
LEFT JOIN `{cfg.dataset}.cb_search_person` cb ON bc.person_id = cb.person_id
"""
    )
