"""Smoke tests for the SQL query builders in :mod:`cohort.queries`.

These tests exercise every public ``*_query`` builder: they assemble the final
SQL string and check it is well-formed, **without ever executing it** against
BigQuery (which is only possible inside the All of Us Researcher Workbench). The
config fixture supplies dummy concept IDs in the shape ``cohort.concepts.resolve``
would populate at runtime, so the builders interpolate real-looking values.
"""

from __future__ import annotations

import inspect

import pytest

import yaml

from cohort import queries
from cohort.config import CohortConfig
from pathlib import Path


def _make_cfg_yaml(enable_drug_exclusions: bool = False) -> CohortConfig:
    cfg_path = Path(__file__).parent / "cfg.yaml"
    with open(cfg_path, "r") as f:
        config = yaml.safe_load(f)
    config["enable_drug_exclusions"] = enable_drug_exclusions
    return CohortConfig(**config)


def _make_cfg(enable_drug_exclusions: bool = False) -> CohortConfig:
    """A fully-resolved config: every concept-ID field populated with dummies."""
    cfg = CohortConfig(dataset="prj.cdr", enable_drug_exclusions=enable_drug_exclusions)
    cfg.hypo_root_concept_ids = [111, 222]
    cfg.t4_ingredient_id = 10582
    cfg.t3_ingredient_id = 777
    cfg.tsh_concept_ids = [3016, 11579, 11580]
    cfg.lab_concept_ids = {"TSH": [3016], "Free T4": [40001], "Anti-TPO": [40002]}
    cfg.interfering_drug_ids = [901, 902]
    cfg.disrupting_drug_ids = [903]
    cfg.desiccated_ingredient_ids = [904]
    cfg = _make_cfg_yaml(enable_drug_exclusions=enable_drug_exclusions)
    return cfg


@pytest.fixture
def cfg() -> CohortConfig:
    return _make_cfg()


def _public_builders():
    """Every ``(name, fn)`` in cohort.queries that builds a final query."""
    out = []
    for name, fn in inspect.getmembers(queries, inspect.isfunction):
        # Only builders defined in this module, public, taking a single cfg arg.
        if fn.__module__ != queries.__name__:
            continue
        if name.startswith("_") or not name.endswith("_query"):
            continue
        out.append((name, fn))
    assert out, "no query builders discovered"
    return out


BUILDERS = _public_builders()
BUILDER_IDS = [name for name, _ in BUILDERS]


# ---------------------------------------------------------------------------
# Every builder produces a well-formed SQL string (no execution)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,fn", BUILDERS, ids=BUILDER_IDS)
def test_builder_returns_wellformed_sql(name, fn, cfg):
    sql = fn(cfg)

    assert isinstance(sql, str) and sql.strip(), f"{name} returned empty SQL"
    # Composed as a single WITH ... SELECT statement.
    assert sql.lstrip().startswith("WITH "), f"{name} does not start with WITH"
    assert sql.count("WITH ") == 1, f"{name} has more than one WITH keyword"
    assert "SELECT" in sql, f"{name} has no SELECT"
    # No unresolved f-string placeholders or un-substituted None concept IDs.
    assert "{" not in sql and "}" not in sql, f"{name} has an unresolved placeholder"
    assert "None" not in sql, f"{name} interpolated a None (unpopulated concept ID)"
    # Parentheses are balanced.
    assert sql.count("(") == sql.count(")"), f"{name} has unbalanced parentheses"


@pytest.mark.parametrize("name,fn", BUILDERS, ids=BUILDER_IDS)
def test_builder_sql_parses_as_bigquery(name, fn, cfg):
    sqlglot = pytest.importorskip("sqlglot")
    sql = fn(cfg)
    # Parse only -- this validates syntax without contacting BigQuery.
    sqlglot.parse_one(sql, dialect="bigquery")


@pytest.mark.parametrize("name,fn", BUILDERS, ids=BUILDER_IDS)
def test_builder_is_deterministic(name, fn, cfg):
    assert fn(cfg) == fn(cfg), f"{name} is not deterministic"


def test_base_cohort_query_builds_with_drug_exclusions():
    cfg = _make_cfg(enable_drug_exclusions=True)
    sql = queries.base_cohort_query(cfg)
    assert "excluded_persons" in sql
    sqlglot = pytest.importorskip("sqlglot")
    sqlglot.parse_one(sql, dialect="bigquery")


# ---------------------------------------------------------------------------
# TSH response classification over the base cohort
# ---------------------------------------------------------------------------


def test_base_tsh_classification_has_four_classes(cfg):
    sql = queries.base_tsh_classification_query(cfg)
    for cls in ("non_responder", "responder", "partial", "insufficient_data"):
        assert f"'{cls}'" in sql, f"base TSH classification missing {cls}"


def test_base_tsh_classification_builds_pre_and_post_tsh_ctes(cfg):
    sql = queries.base_tsh_classification_query(cfg)
    assert "pre_tsh AS (" in sql
    assert "post_tsh AS (" in sql
    # Classifies the base cohort, not a symptom cohort.
    assert "base_cohort" in sql
    assert "ehr_symptom_cohort" not in sql
    assert "survey_symptom_cohort" not in sql


def test_base_tsh_classification_interpolates_thresholds(cfg):
    sql = queries.base_tsh_classification_query(cfg)
    # Pre-treatment lookback window and on-treatment horizon.
    assert f"INTERVAL {cfg.pre_tsh_lookback_days} DAY" in sql
    assert f"INTERVAL {cfg.post_tsh_min_days} DAY" in sql
    assert f"INTERVAL {cfg.classify_post_max_days} DAY" in sql
    # Normalization / elevation cutoffs and the sustained-measurement count.
    assert f"> {cfg.tsh_elevated}" in sql
    assert f"BETWEEN {cfg.tsh_normal_low} AND {cfg.tsh_normal_high}" in sql
    assert f">= {cfg.min_post_measurements}" in sql


def test_base_tsh_classification_parses_as_bigquery(cfg):
    sqlglot = pytest.importorskip("sqlglot")
    sql = queries.base_tsh_classification_query(cfg)
    sqlglot.parse_one(sql, dialect="bigquery")


# ---------------------------------------------------------------------------
# Symptom response classification: responders / non-responders / confirmed
# ---------------------------------------------------------------------------


def test_ehr_symptom_classification_has_three_classes(cfg):
    sql = queries.ehr_symptom_classification_query(cfg)
    print(sql)
    assert "symptom_nonresponder" in sql
    assert "symptom_responder" in sql
    assert "no_pre_symptom" in sql
    # EHR is presence-based: no survey-answer machinery leaks in.
    assert "symptom_responder_confirmed" not in sql
    assert "ppi_absent_answer_concepts" not in sql
    assert "value_as_concept_id" not in sql


def test_survey_symptom_classification_has_confirmed_class(cfg):
    sql = queries.survey_symptom_classification_query(cfg)
    for cls in (
        "symptom_nonresponder",
        "symptom_responder_confirmed",
        "symptom_responder",
        "no_pre_symptom",
    ):
        assert cls in sql, f"survey classification missing {cls}"
    # The confirmed class is driven by the coded PPI answer value.
    assert "ppi_absent_answer_concepts" in sql
    assert "value_as_concept_id" in sql


@pytest.mark.parametrize(
    "builder,flag,klass",
    [
        (
            "ehr_symptom_nonresponder_query",
            "ehr_symptom_nonresponder",
            "symptom_nonresponder",
        ),
        ("ehr_symptom_responder_query", "ehr_symptom_responder", "symptom_responder"),
        (
            "survey_symptom_nonresponder_query",
            "survey_symptom_nonresponder",
            "symptom_nonresponder",
        ),
        (
            "survey_symptom_responder_query",
            "survey_symptom_responder",
            "symptom_responder",
        ),
        (
            "survey_symptom_responder_confirmed_query",
            "survey_symptom_responder_confirmed",
            "symptom_responder_confirmed",
        ),
    ],
)
def test_symptom_filter_queries(cfg, builder, flag, klass):
    sql = getattr(queries, builder)(cfg)
    assert f"TRUE AS {flag}" in sql, f"{builder} missing flag column {flag}"
    assert f"= '{klass}'" in sql, f"{builder} does not filter to {klass}"


def test_confirmed_query_is_survey_only():
    # There is no EHR equivalent of the answer-confirmed responder class.
    assert not hasattr(queries, "ehr_symptom_responder_confirmed_query")
