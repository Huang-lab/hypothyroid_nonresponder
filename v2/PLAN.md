# Hypothyroidism T4 Non-Responder Cohort — Study Plan (v2)

## Objective

Identify hypothyroidism patients who **do not respond to levothyroxine (T4)** treatment, with a
phenotype clean enough to support a future genetic/biomarker study of non-response. This version
sharpens the non-responder definition to reduce misclassification; it does **not** yet implement
the GWAS analysis itself or weight-based dose-adequacy (see *Deferred*, below).

Platform: **All of Us Researcher Workbench** (BigQuery over the OMOP CDM). This is the protocol of
record — when cohort criteria change in code, update this file to match.

## Why phenotype precision matters here

A "non-responder" who is really just under-dosed, non-adherent, malabsorbing, or confounded
(pregnancy, central hypothyroidism, suppressed TSH for thyroid cancer) dilutes any downstream
genetic signal. Every inclusion/exclusion criterion below exists to separate *biological*
non-response from these mimics.

## Base cohort (denominator)

A person qualifies when **all** hold. Thresholds are fields on `CohortConfig` (`cohort/config.py`).

1. **Confirmed hypothyroidism** — ≥ 2 diagnoses on separate dates, matched by OR of two paths:
   - *Path 1 (primary):* `condition_concept_id` is a descendant of a SNOMED hypothyroidism root
     (40930001 Hypothyroidism, 21983002 Hashimoto thyroiditis) via `concept_ancestor`.
   - *Path 2 (safety net):* `condition_source_concept_id` maps to an ICD-10 (E00–E03, E06.3) or
     ICD-9 (243, 244.x) hypothyroidism code.
2. **Adult at treatment start** — age ≥ 18 at first T4.
3. **T4 within the eligibility window** — first levothyroxine exposure on/after diagnosis and
   within `t4_window_days` (default 365) after it; never before diagnosis.
4. **Elevated pre-treatment TSH** — a TSH > `pre_tsh_elevated` (default 4.2 mIU/L) within
   `pre_tsh_lookback_days` before diagnosis, confirming genuine hypothyroidism needing treatment.
5. **On-treatment TSH available** — at least one TSH measurement at steady state
   (`post_tsh_min_days`–`post_tsh_avail_max_days`, default 90–180 days after T4).
6. **T3 not co-started** — no liothyronine within `t3_coexclusion_days` (default 90) of T4.
7. **Not excluded** — none of the exclusion conditions below.

### Exclusions (mimics of non-response / confounded TSH)

Condition-based, matched by ICD source code. Structural conditions are "ever"; pregnancy is windowed
around treatment. Lists live in `cohort/config.py`.

- **Malabsorption / altered absorption** — celiac, IBD, post-GI-surgery / bariatric status.
- **Central (secondary) hypothyroidism** — hypopituitarism; TSH is an invalid response marker.
- **Thyroid cancer** — TSH is deliberately suppressed, so response would be misclassified.
- **Pregnancy / puerperium** — shifted TSH targets and rising dose needs, within the treatment window.

*Optional (off by default, `enable_drug_exclusions`):* drugs that interfere with T4 absorption
(PPIs, calcium, iron, bile-acid sequestrants, sucralfate), drugs that independently disrupt thyroid
function (amiodarone, lithium, interferon, checkpoint inhibitors, TKIs), and desiccated-thyroid
co-treatment. Off by default because co-prescription is a crude proxy (administration timing is not
captured) and may remove too many members.

## Nested symptom cohorts

Each is the base cohort plus one symptom-based inclusion filter, with its own non-responder queries:

- **EHR symptom cohort** — ≥ 1 target symptom in `condition_occurrence` (ICD-10) in the year before
  diagnosis.
- **Survey symptom cohort** — ≥ 1 target symptom reported in PPI survey `observation` records before
  diagnosis.

Target symptoms (`HYPO_SYMPTOMS` / `PPI_SYMPTOM_KEYWORDS`): **fatigue**, **constipation**,
**brain fog** (cognitive impairment).

## Non-responder classification

Applied per cohort.

1. **TSH non-responder (primary, objective).** From sustained on-treatment TSH over
   `post_tsh_min_days`–`classify_post_max_days` (default 90–730):
   - `non_responder`: ≥ `min_post_measurements` (default 2) measurements, **none** normalized
     (0.4–4.0), and ≥ 2 elevated (> 4.0).
   - `responder`: ≥ 2 normalized measurements.
   - else `partial` (some data) / `insufficient_data` (no on-treatment TSH).
2. **T3 add-on non-responder.** Liothyronine started after the co-start window but within
   `t3_nonresponder_window_days` (default 180) of T4 — escalation off T4 monotherapy.
3. **Symptom-persistence non-responder** *(symptom cohorts only).* A target symptom present before
   T4 is still present `symptom_post_min_days`–`symptom_post_max_days` after T4.

## Feasibility deliverables (Phase 1)

1. Base cohort size; EHR and survey symptom cohort sizes.
2. Response-class counts (non-responder / responder / partial / insufficient) per cohort.
3. T3 add-on and symptom-persistence non-responder counts.
4. **Lab-data availability** — base-cohort members with each thyroid analyte
   (TSH, free/total T4, free/total T3, reverse T3, anti-TPO, anti-Tg, TSI, TBG).
5. **Genomic-data availability** — base-cohort overlap with WGS / genotyping-array data
   (`cb_search_person`). This count decides whether a genetic analysis is feasible at all.

## Deferred (pending data-availability checks)

Intentionally **not** implemented yet, because the required data may be sparse or absent in All of Us:

- **Weight-based T4 dose adequacy** (µg/kg/day) — would require reliable drug strength + body weight,
  to define non-response as elevated TSH *despite an adequate dose* and to flag non-adherence.
- **GWAS-specific criteria** — genetic ancestry handling, principal components, relatedness, and the
  association analysis (REGENIE/SAIGE), plus positive-control loci (e.g. DIO2 rs225014). These belong
  to a later phase once feasibility (deliverable 5) is established.

## Implementation

- Package: `cohort/` (`config`, `concepts`, `ctes`, `queries`, `runner`, `sqlutil`).
- Notebook (thin orchestrator): `hypothyroidism_nonresponder_cohort.ipynb`.
- See `README.md` for the composition model and how to extend it.
