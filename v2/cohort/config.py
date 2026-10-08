"""Cohort configuration: tunable thresholds, code lists, and resolved concept IDs.

Everything that defines *who is in the cohort* lives here or is derived from here.
Clinical thresholds are plain fields on :class:`CohortConfig` so a single edit
propagates to every CTE and query. Concept IDs are **not** hardcoded -- they are
discovered from the CDR vocabulary at runtime (see :mod:`cohort.concepts`) and
stored back onto the config object. The deliberate exceptions are ICD source
codes, kept as explicit literals to serve as a mapping safety net.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# ICD source-code safety nets (deliberately hardcoded).
# Matched against condition_source_concept_id to catch records whose
# source->standard mapping is absent or maps to a non-target standard concept.
# ---------------------------------------------------------------------------

# Hypothyroidism inclusion codes.
HYPO_ICD10 = [
    "E00", "E00.0", "E00.1", "E00.2", "E00.9",
    "E01", "E01.0", "E01.1", "E01.2", "E01.8",
    "E02",
    "E03", "E03.0", "E03.1", "E03.2", "E03.3", "E03.4", "E03.8", "E03.9",
    "E06.3",
]
HYPO_ICD9 = ["243", "244", "244.0", "244.1", "244.2", "244.3", "244.8", "244.9"]

# ---------------------------------------------------------------------------
# Exclusion code lists (mimics of non-response / confounded TSH).
# Condition-based exclusions are matched by ICD source code, by category so the
# reason for each exclusion stays auditable. Pregnancy is applied with a time
# window around treatment; the rest are treated as "ever".
# ---------------------------------------------------------------------------

# Malabsorption / altered levothyroxine absorption.
EXCL_MALABSORPTION_ICD10 = [
    "K90.0",            # celiac disease
    "K90.9",            # intestinal malabsorption, unspecified
    "K50", "K50.0", "K50.1", "K50.8", "K50.9",   # Crohn's
    "K51", "K51.0", "K51.2", "K51.3", "K51.5", "K51.8", "K51.9",  # ulcerative colitis
    "K91.1",            # postgastric surgery syndromes
    "K91.2",            # postsurgical malabsorption
    "Z90.3",            # acquired absence of part of stomach
    "Z98.84",           # bariatric surgery status
]
EXCL_MALABSORPTION_ICD9 = ["579.0", "555", "556", "564.2", "V45.3"]

# Central / secondary hypothyroidism (TSH is an invalid response marker here).
EXCL_CENTRAL_ICD10 = ["E23.0", "E23.1"]
EXCL_CENTRAL_ICD9 = ["253.2", "253.3", "253.4"]

# Thyroid cancer (TSH is deliberately suppressed, so response is misclassified).
EXCL_THYROID_CANCER_ICD10 = ["C73"]
EXCL_THYROID_CANCER_ICD9 = ["193"]

# Pregnancy / puerperium (shifted TSH targets and rising dose requirements).
# Applied within a window around treatment, not "ever".
EXCL_PREGNANCY_ICD10 = [
    "Z33.1", "Z34", "Z34.0", "Z34.8", "Z34.9", "Z3A",
    "O99", "O99.0", "O99.1", "O99.2", "O99.3",
]
EXCL_PREGNANCY_ICD9 = ["V22", "V22.0", "V22.1", "V22.2", "V23", "650"]

# ---------------------------------------------------------------------------
# Drug-based exclusions (OPTIONAL -- off by default).
# Discovered by RxNorm ingredient name. Co-prescription is a crude proxy for
# true interference (timing of administration matters and is not captured), so
# these are disabled unless cfg.enable_drug_exclusions is set.
# ---------------------------------------------------------------------------

# Drugs that interfere with levothyroxine absorption when co-administered.
INTERFERING_DRUG_NAMES = [
    "omeprazole", "esomeprazole", "pantoprazole", "lansoprazole",  # PPIs
    "calcium carbonate", "ferrous sulfate",                     # cation binders
    "cholestyramine", "colesevelam",                            # bile-acid sequestrants
    "sucralfate",
]

# Drugs that independently cause thyroid dysfunction.
THYROID_DISRUPTING_DRUG_NAMES = [
    "amiodarone", "lithium", "lithium carbonate",
    "interferon alfa-2b", "peginterferon alfa-2a",
    "nivolumab", "pembrolizumab", "ipilimumab",   # checkpoint inhibitors
    "sunitinib", "sorafenib",                      # tyrosine kinase inhibitors
]

# Desiccated-thyroid ingredient name (co-treatment confounds TSH interpretation).
DESICCATED_THYROID_NAME = "thyroid"

# ---------------------------------------------------------------------------
# Thyroid lab panel -- name-based discovery patterns (data availability).
# LOINC concepts are resolved from the vocabulary by name rather than hardcoded
# codes, then reviewed. TSH additionally anchors on known LOINC codes.
# ---------------------------------------------------------------------------

TSH_LOINC_CODES = ["3016-3", "11579-0", "11580-8"]

LAB_NAME_PATTERNS = {
    "TSH": ["%thyrotropin%", "%thyroid stimulating hormone%"],
    "Free T4": ["%thyroxine (t4) free%", "%free t4%", "%ft4%"],
    "Total T4": ["%thyroxine (t4)%"],
    "Free T3": ["%triiodothyronine (t3) free%", "%free t3%", "%ft3%"],
    "Total T3": ["%triiodothyronine (t3)%"],
    "Reverse T3": ["%reverse triiodothyronine%", "%reverse t3%"],
    "Anti-TPO": ["%thyroid peroxidase ab%", "%thyroperoxidase%", "%tpo ab%"],
    "Anti-Tg": ["%thyroglobulin ab%", "%thyroglobulin antibody%"],
    "TSI": ["%thyroid stimulating immunoglobulin%"],
    "TBG": ["%thyroxine binding globulin%"],
}

# ---------------------------------------------------------------------------
# Target symptoms for the symptom-based cohorts.
# ---------------------------------------------------------------------------

HYPO_SYMPTOMS = {
    "fatigue": ["R53.83", "R53.1", "R53.81"],
    "constipation": ["K59.00", "K59.09"],
    "brain_fog": ["R41.3", "R41.89", "F06.8"],
}

PPI_SYMPTOM_KEYWORDS = {
    "fatigue": ["%fatigue%", "%tired%", "%energy%"],
    "constipation": ["%constipat%"],
    "brain_fog": ["%concentrate%", "%memory%", "%cognitive%", "%brain fog%"],
}

# PPI survey *answer* values that affirm a symptom is ABSENT / resolved ("gone").
# Matched (by keyword, case-insensitive) against PPI answer concept names so a
# post-treatment survey answer can positively confirm resolution rather than
# inferring it from a missing record. Review the matched concepts before relying
# on them -- PPI answer wording varies by survey module.
PPI_ABSENT_ANSWER_KEYWORDS = [
    "%not at all%",
    "%none of the time%",
    "%never%",
    "%no symptoms%",
    "%symptom-free%",
]


@dataclass
class CohortConfig:
    """All tunable parameters plus the concept IDs resolved at runtime.

    Create one, call :func:`cohort.concepts.resolve` to populate the discovered
    fields, then pass it to the CTE/query builders in :mod:`cohort.ctes` and
    :mod:`cohort.queries`.
    """

    dataset: str

    # --- Inclusion thresholds ---------------------------------------------
    min_dx_count: int = 2                 # >=2 hypothyroid dx on separate dates
    min_age_at_t4: int = 18               # adults only
    pre_tsh_elevated: float = 4.2         # pre-treatment TSH confirming disease
    pre_tsh_lookback_days: int = 365      # window before diagnosis for pre-TSH
    t4_window_days: int = 365             # T4 must start within 1yr after dx
    post_tsh_min_days: int = 90           # steady state: earliest post-T4 TSH
    post_tsh_avail_max_days: int = 180    # availability gate: a TSH in 3-6 mo
    t3_coexclusion_days: int = 90         # T3 not co-started within 3 mo of T4

    # --- Response classification ------------------------------------------
    tsh_normal_low: float = 0.4
    tsh_normal_high: float = 4.0
    tsh_elevated: float = 4.0             # on-treatment "not normalized" cutoff
    classify_post_max_days: int = 730     # horizon for sustained classification
    min_post_measurements: int = 2        # >=2 on-treatment TSH to classify
    t3_nonresponder_window_days: int = 180  # T3 add-on after T4 => T3 non-responder

    # --- Symptom windows ---------------------------------------------------
    symptom_lookback_days: int = 365      # pre-diagnosis symptom window
    symptom_post_min_days: int = 90       # earliest post-T4 symptom (persistence)
    symptom_post_max_days: int = 365      # latest post-T4 symptom (persistence)

    # --- Optional modules --------------------------------------------------
    enable_drug_exclusions: bool = False  # interfering / disrupting / desiccated

    # --- Resolved concept IDs (filled by cohort.concepts.resolve) ---------
    hypo_root_concept_ids: list[int] = field(default_factory=list)
    t4_ingredient_id: int | None = None
    t3_ingredient_id: int | None = None
    tsh_concept_ids: list[int] = field(default_factory=list)
    lab_concept_ids: dict[str, list[int]] = field(default_factory=dict)
    interfering_drug_ids: list[int] = field(default_factory=list)
    disrupting_drug_ids: list[int] = field(default_factory=list)
    desiccated_ingredient_ids: list[int] = field(default_factory=list)
