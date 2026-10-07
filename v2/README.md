# hypotnr v2 — modular cohort builder

A restructured, importable version of the hypothyroidism T4 non-responder study. The one-notebook
v1 (SQL CTE f-strings inline) is reorganized into a small Python package with a thin orchestration
notebook, and the non-responder phenotype is tightened for precision (see `PLAN.md`).

Runs only inside the **All of Us Researcher Workbench** (BigQuery / OMOP CDM). It needs the
`WORKSPACE_CDR` env var and ambient GCP credentials — there is no way to execute the queries locally.

## Layout

```
v2/
├── cohort/
│   ├── runner.py     # Runner: BigQuery client + df()/scalar()/run() bound to WORKSPACE_CDR
│   ├── config.py     # CohortConfig (thresholds), ICD/keyword code lists, lab/symptom definitions
│   ├── concepts.py   # data-driven concept-ID discovery from the CDR vocabulary -> cfg
│   ├── sqlutil.py    # tiny SQL string helpers (id lists, WITH clause, concept-id CTEs)
│   ├── ctes.py       # reusable building-block CTE fragments, composed from a CohortConfig
│   └── queries.py    # assembled, runnable queries (cohorts, classification, feasibility)
├── hypothyroidism_nonresponder_cohort.ipynb   # thin orchestrator
├── PLAN.md           # protocol of record (cohort definitions, thresholds, deliverables)
├── setup.cfg         # lint config (line length)
└── README.md
```

## Composition model

The design is the same idea as v1 — **reusable SQL CTE fragments** — but as functions of a config
object instead of module-level globals:

1. **`CohortConfig`** holds every tunable threshold and, after discovery, the resolved concept IDs.
   One edit to a threshold propagates to every query.
2. **`concepts.resolve(runner, cfg)`** queries `concept` / `concept_ancestor` to fill the concept-ID
   fields (SNOMED roots, RxNorm T4/T3 ingredients, TSH + lab LOINC concepts). IDs are discovered,
   not hardcoded; ICD source codes are the deliberate exception (a mapping safety net).
3. **`ctes.*`** each return one named CTE string (no leading comma). `base_cohort_ctes(cfg)` returns
   the ordered list that defines `base_cohort`.
4. **`queries.*`** join the CTEs with `sqlutil.with_clause` and add the final `SELECT`. Because every
   query is built from the same building blocks, a cohort-definition change propagates everywhere.

## Usage

```python
from cohort import CohortConfig, Runner, concepts, queries

runner = Runner()                          # WORKSPACE_CDR + ambient creds
cfg = CohortConfig(dataset=runner.dataset)
concepts.resolve(runner, cfg)              # discover concept IDs (review the returned frames)

df_base = runner.df(queries.base_cohort_query(cfg))
df_cls  = runner.df(queries.base_tsh_classification_query(cfg))
print(df_cls["response_class"].value_counts())
```

Run the notebook top-to-bottom: discovery cells must run before query cells (the queries read the
IDs discovery wrote onto `cfg`).

## Tuning the cohort

Change a field on `cfg` before building queries — e.g.:

```python
cfg.pre_tsh_elevated = 4.5          # stricter pre-treatment TSH
cfg.min_post_measurements = 3       # require 3 on-treatment TSH to classify
cfg.enable_drug_exclusions = True   # add interfering/disrupting-drug exclusions
concepts.resolve(runner, cfg)       # re-resolve if you toggled drug exclusions
```

## What's deliberately not here

Weight-based T4 dose adequacy and the GWAS analysis itself are **deferred** pending data-availability
checks — see *Deferred* in `PLAN.md`. The notebook's feasibility section (lab + genomic availability)
is what determines whether those next phases are viable.

## Editing locally

`source ve` (from the repo root) activates the editing venv for linting only. The SQL builders are
pure string functions, so you can smoke-test composition without BigQuery:

```python
from cohort.config import CohortConfig
from cohort import queries
cfg = CohortConfig(dataset="proj.cdr")
cfg.hypo_root_concept_ids=[40930001]; cfg.t4_ingredient_id=1; cfg.t3_ingredient_id=2
cfg.tsh_concept_ids=[3016]
print(queries.base_cohort_query(cfg))   # inspect the generated SQL
```
