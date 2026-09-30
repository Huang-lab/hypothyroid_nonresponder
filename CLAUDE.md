# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-notebook epidemiology study that runs on the **All of Us Researcher Workbench**
(BigQuery over the OMOP CDM). The goal (see `PLAN.md`) is to identify hypothyroidism patients
who do not respond to T4 (levothyroxine) treatment, as a feasibility step toward discovering
genetic/proteomic biomarkers of non-response.

All work lives in `hypothyroidism_allofus_query.ipynb`. `PLAN.md` is the study protocol and the
source of truth for cohort definitions, clinical thresholds, and deliverables.

## Environment

The notebook only runs inside the All of Us Researcher Workbench. It depends on:
- `WORKSPACE_CDR` env var — the versioned CDR BigQuery dataset, read into the global `DATASET`.
- Ambient GCP credentials for `bigquery.Client()` (provided by the workbench).

It cannot be executed outside that environment; there is no way to run the queries locally.
Local venv for editing/linting only:
```bash
source ve          # equivalent to: source .venv_hypotnr/bin/activate
```
There are no build, lint, or test commands — this is an analysis notebook, run cell by cell.

## Architecture

The notebook composes **reusable SQL CTE fragments as Python f-strings**, then injects them into
downstream queries. Understanding this composition model is the key to working here.

1. **Concept-ID discovery (cells ~4–7).** Concept IDs are resolved dynamically from the CDR vocab
   rather than hardcoded, and stored in module-level globals:
   - `ROOT_CONCEPT_IDS` — SNOMED root concepts for hypothyroidism/Hashimoto's.
   - `HYPO_ICD10` / `HYPO_ICD9` — literal ICD source-code lists (safety net for unmapped records).
   - `t4_concept_id` / `t3_concept_id` — RxNorm ingredient IDs for levothyroxine / liothyronine.

2. **Building-block CTEs (cell ~12).** Named CTE strings that interpolate the globals above:
   `HYPO_DIAG_CTE`, `TSH_CTE`, `T4_FIRST_CTE`, `T3_FIRST_CTE`, `BASE_COHORT_CTE`,
   `HYPO_SYMPTOM_CONCEPTS_CTE`, `PPI_SYMPTOM_CONCEPTS_CTE`. Each holds one or more comma-joined
   CTE definitions with **no leading comma**; `BASE_COHORT_CTE` depends on the four CTEs before it.

3. **Query assembly.** Every query is `f"WITH {TSH_CTE},\n{HYPO_DIAG_CTE},\n... SELECT ..."`.
   Execute via the helpers in the setup cell: `run_query(sql) -> DataFrame` and
   `run_query_scalar(sql)`.

**Cell order matters.** Globals must be defined before the CTE cell interpolates them, which must
run before any query cell. Run the notebook top-to-bottom; re-running a query cell after editing a
concept list requires re-running the CTE cell first.

### Cohorts

Three nested cohorts, each built on `base_cohort` with one additional inclusion filter, and each
followed by its own non-responder classification queries:
- **Base Cohort** — hypothyroid dx + first T4 within eligibility window + pre-dx TSH > 4.2 +
  post-T4 TSH measurement (3–6 mo) + T3 not co-started. All thresholds are defined in
  `BASE_COHORT_CTE`.
- **EHR Symptom Cohort** — base + ≥1 target symptom (ICD-10) in EHR in the year before diagnosis.
- **Survey Symptom Cohort** — base + ≥1 target symptom in PPI survey observations.

Non-responder classification compares pre- vs. post-treatment TSH (and symptom persistence).
Target symptoms and their ICD-10 / PPI-keyword mappings live in `HYPO_SYMPTOMS` and
`PPI_SYMPTOM_KEYWORDS` (cell ~11).

### OMOP tables used
`condition_occurrence`, `drug_exposure`, `measurement`, `observation`, `concept`,
`concept_ancestor` — all referenced as `` `{DATASET}.<table>` ``.

## Conventions

- Keep concept selection data-driven (query the vocab for IDs) rather than hardcoding numeric
  concept IDs; ICD source codes are the deliberate exception (Path 2 safety net in `PLAN.md`).
- When adding a query, build it from the existing building-block CTEs instead of re-writing cohort
  logic inline, so a cohort-definition change propagates to every query.
- When cohort criteria change, update `PLAN.md` to match — it is the protocol of record.
