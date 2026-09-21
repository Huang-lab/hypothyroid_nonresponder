# Hypothyroidism Treatment Non-Responder Biomarker Study — Plan

## Objective

Identify genetic or proteomic biomarkers associated with hypothyroidism patients who do not respond to T4 (levothyroxine) treatment.

## Phase 1: Data Availability Assessment (All of Us Research Program)

The first step is to determine whether the All of Us dataset contains sufficient data to support this research.

### 1.1 Hypothyroidism Cohort Identification

Cohort membership is determined by an OR of two independent matching paths, applied to
`condition_occurrence`:

**Path 1 — Standard concept hierarchy (primary)**
Use `concept_ancestor` to traverse the full SNOMED condition hierarchy from two root concepts:
- SNOMED 40930001 — Hypothyroidism (covers all subtypes including myxedema, cretinism,
  thyroid atrophy, post-ablative hypothyroidism, drug-induced hypothyroidism, etc.)
- SNOMED 21983002 — Hashimoto thyroiditis (autoimmune; may occupy a separate branch
  under thyroiditis rather than directly under hypothyroidism)

This approach captures every child condition in the OMOP hierarchy automatically,
without requiring manual enumeration of individual codes.

**Path 2 — Source code safety net (supplementary)**
Match `condition_source_concept_id` against explicit ICD code lists to capture records
where source-to-standard concept mapping is absent or maps to a non-hypothyroid standard concept:
- ICD-10-CM: E00–E03 range (all hypothyroidism subtypes), E06.3 (Hashimoto's)
- ICD-9-CM: 243, 244.x

### 1.2 Thyroid-Related Lab Results

For cohort members, retrieve all measurements for hypothyroidism-relevant biomarkers:
- **TSH** (thyroid-stimulating hormone) — primary marker of thyroid function
- **Free T4 / Total T4** — primary treatment hormone
- **Free T3 / Total T3** — active form; relevant in T4-only treatment non-response
- **Reverse T3** — marker of impaired T4-to-T3 conversion
- **Anti-TPO antibodies** — marker of autoimmune (Hashimoto's) etiology
- **Anti-thyroglobulin antibodies**
- **Thyroid-stimulating immunoglobulin (TSI)**
- **Thyroid binding globulin (TBG)**

### 1.3 T4 Treatment Exposure

Identify individuals with documented levothyroxine prescriptions or dispensings using:
- RxNorm ingredient concept 10582 (levothyroxine) and all descendant drug concepts
- Capture treatment index date (first prescription after diagnosis)
- Calculate days supply and treatment continuity

### 1.4 Treatment Response Assessment

Determine whether each treated individual responded to T4 therapy using two data streams:

**Biochemical response (objective):**
- Longitudinal TSH values before and after treatment initiation
- Response defined as TSH normalization (0.4–4.0 mIU/L) on ≥ 2 measurements at least 90 days post-treatment
- Non-responder defined as TSH remaining > 4.0 mIU/L on all post-treatment measurements

**Symptom-based response (clinical):**

Query ICD-10 codes for hypothyroidism-associated symptoms, stratified pre- vs. post-treatment:
- Fatigue (R53.x)
- Insomnia (G47.0x)
- Constipation (K59.0x)
- Cold intolerance (R68.89)
- Weight gain (R63.5)
- Depression (F32.x, F33.x)
- Dry skin (L85.3, R23.8)
- Hair loss (L65.9, L66.9)
- Bradycardia (R00.1)
- Cognitive impairment / brain fog (R41.3, R41.89, F06.8)
- Myalgia (M79.3)
- Edema (R60.x)
- Dyslipidemia (E78.x) — commonly secondary to hypothyroidism

**Patient-reported outcomes (subjective):**
- All of Us PPI (Program for Patient Insights) survey data for self-reported fatigue, sleep quality, energy levels, and cognitive symptoms

### 1.5 Genomic and Proteomic Data Availability

Assess overlap between the hypothyroid cohort and available multi-omic data:
- Whole genome sequencing (WGS)
- Genotyping array data
- Survey and Fitbit data (for longitudinal symptom tracking)

Use the `cb_search_person` table to enumerate data modality availability per participant.

## Deliverables for Phase 1

1. Total hypothyroid cohort size
2. Subset with thyroid lab data (by lab type)
3. Subset with documented T4 treatment
4. Subset with sufficient pre- and post-treatment TSH for response classification
5. Response classification counts (responder / non-responder / partial / insufficient data)
6. Genomic data overlap count — determines feasibility of biomarker discovery phase

## Implementation

- Notebook: `hypothyroidism_allofus_query.ipynb`
- Platform: All of Us Researcher Workbench (BigQuery / OMOP CDM)
- Language: Python 3, `google-cloud-bigquery`, `pandas`, `matplotlib`, `seaborn`
