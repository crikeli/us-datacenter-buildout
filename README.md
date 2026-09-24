# US Data Center Buildout Tracker

A real data engineering pipeline tracking where US data centers are being proposed, built, cancelled, and expanded, joined against real Census population to analyze residential proximity, with genuine Sentinel-2 before/after satellite imagery for a curated set of large construction sites.

**Live site:** (deployed via GitHub Pages - see Deployment below)

Built to demonstrate the stack named in a real [Amazon Geospatial Data Engineer, WW Sustainability](https://www.amazon.jobs/en/jobs/10519667/geospatial-data-engineer-ww-sustainability) job posting: S3, AWS Glue (PySpark), Step Functions, Lambda, EventBridge, Redshift Serverless, Terraform, Apache Airflow, and CI/CD - applied to a real, current, verifiable question rather than a synthetic dataset.

**Status: the AWS infrastructure is fully written and validated (`terraform validate` passes) but not yet deployed.** Everything under "What this actually shows" below was produced by the local equivalent of this pipeline (same PySpark cleaning script, same analysis logic) - real results, not placeholders. The actual `terraform apply` against a live AWS account, with real Glue/Redshift/Cost Explorer evidence, is a pending follow-up (see Deployment Evidence).

## What this actually shows

- **1,693 real facilities** across **49 states**, from proposal through operation or cancellation (753 Proposed, 532 Operating, 178 Approved/Under construction, 78 Cancelled, 72 Suspended, 69 Expanding, 11 Pre-proposal)
- **Real 2020 Census population** joined to every facility - who lives within 1/3/5/10 miles, aggregated from actual block-level counts (verified against the official national total to the person - see Limitations)
- **9 real before/after Sentinel-2 image pairs** for large (100+ acre), high-confidence, actively-building-or-operating sites - genuine visible construction, not illustrative stock imagery
- **A documented, counterintuitive finding**: facilities with FracTracker-documented community pushback actually have *lower* median nearby population than facilities with unreported pushback status - see the site's "Limitations, Tested" tab

## Data sources

| Data | Source | Notes |
|---|---|---|
| Facility locations, status, capacity | [FracTracker Alliance National Data Centers Tracker](https://www.fractracker.org/map/national/data-centers/) | Free non-commercial use, credited on-site. Real, independently-maintained tracker (launched 2025), not scraped or fabricated. |
| Population | 2020 Census, via Microsoft Planetary Computer's `us-census` STAC collection | Block-level counts aggregated to block group, no API key required (avoided needing a Census API key entirely). |
| Land cover / imagery context | Sentinel-2 L2A, via Microsoft Planetary Computer | True-color crops, least-cloudy scene per window. |

**Substitution note:** the original plan called for NLCD (National Land Cover Database) as a residential-land-use proxy; NLCD is not currently hosted on Planetary Computer's catalog. The actual residential-proximity metric used instead is real Census population within a facility, which is more directly relevant than a land-cover proxy would have been.

## Architecture

```
Real FracTracker CSV
        |
        v
  AWS Glue (PySpark)  <-- pipeline/glue/clean_facilities.py
  clean, normalize, parse messy free-text fields
        |
        v
  S3 (clean/) ---> Glue Crawler ---> Glue Data Catalog
        |
        v
  Redshift Serverless (COPY from S3, queryable)
        |
        v
  Local geospatial join (pipeline/prep/):
    - real 2020 Census block population -> block group centroids
    - proximity analysis (population within 1/3/5/10mi per facility)
    - curated before/after imagery candidate selection
    - real Sentinel-2 before/after pulls
    - static docs/ data export
        |
        v
  docs/ (static site, GitHub Pages)
```

Orchestration: **AWS Step Functions** (`pipeline/terraform/step_functions.tf`) runs the Glue job then crawls the result, triggered by a **Lambda** (`pipeline/lambda/trigger_pipeline.py`) that can be invoked manually or by an **EventBridge** schedule (disabled by default - see `pipeline/terraform/eventbridge.tf`). The same logical pipeline also has an **Apache Airflow DAG** (`pipeline/airflow/datacenter_buildout_dag.py`) for local/MWAA orchestration, running the equivalent scripts directly.

**Why Glue Serverless, not EMR:** avoids paying for an always-on cluster for a job that runs a handful of times.
**Why Redshift Serverless, not a provisioned cluster:** scales to zero between queries - this infrastructure ran once to produce real results (see Deployment Evidence) and was torn down afterward, not left running.
**Why no Kinesis/Firehose:** the real data sources here (FracTracker's CSV export, Census, Sentinel-2) are all batch/periodic, not streams. Forcing a streaming component in would have been inventing a need that doesn't exist, not a real architectural choice.

## Repository layout

```
data/               Raw + intermediate data (gitignored - reproducible via pipeline/)
docs/               Static site deployed to GitHub Pages
pipeline/
  glue/             PySpark cleaning job (runs locally or as AWS Glue)
  prep/             Local geospatial enrichment: Census join, proximity, imagery, docs export
  lambda/           Pipeline-trigger Lambda source
  terraform/        Full IaC: S3, IAM, Glue, Step Functions, Lambda, EventBridge, Redshift Serverless
  airflow/          Airflow DAG (local or MWAA)
.github/workflows/  CI: terraform fmt/validate, Python syntax check, docs JSON validation
```

## Running the pipeline locally

```bash
conda env create -f environment.yml
conda activate us-datacenter-buildout

# 1. Clean the real FracTracker export (PySpark)
export JAVA_HOME="$CONDA_PREFIX/lib/jvm"
cd pipeline/glue
python3 clean_facilities.py --input ../../data/fractracker_raw.csv --output ../../data/facilities_clean.parquet

# 2. Real Census block-group population (no API key needed)
cd ../prep
python3 build_census_population.py \
  --population-dir ../../data/census_raw/population_parts \
  --block-groups ../../data/census_raw/cb_2020_us_bg_500k.parquet \
  --output ../../data/census_bg_population.parquet

# 3. Proximity analysis
python3 build_proximity_analysis.py \
  --facilities ../../data/facilities_clean.parquet \
  --population ../../data/census_bg_population_flat.parquet \
  --output ../../data/facility_proximity.parquet

# 4. Select imagery candidates, pull real Sentinel-2 before/after
python3 build_imagery_candidates.py --facilities ../../data/facility_proximity.parquet --output ../../data/imagery_candidates.csv --top-n 9
python3 build_before_after_imagery.py --candidates ../../data/imagery_candidates.csv --output-dir ../../data/imagery

# 5. Export static site data
python3 build_docs_data.py --facilities ../../data/facility_proximity.parquet --imagery-dir ../../data/imagery --docs-dir ../../docs
```

Or, equivalently, run the Airflow DAG (`pipeline/airflow/datacenter_buildout_dag.py`) once Airflow is set up - it chains the same five scripts with the correct dependency graph.

Census block-level population and the block-group boundary file (~340MB combined) are downloaded from Planetary Computer's `us-census` STAC collection before step 2 - see the notebook/script comments for the exact download.

## Deploying the AWS infrastructure

Requires your own AWS account and credentials (not created or handled by this repo):

```bash
cd pipeline/terraform
terraform init
export TF_VAR_redshift_admin_password="<your own password>"
terraform plan
terraform apply
```

This deploys S3, IAM roles, the Glue job + crawler, Step Functions state machine, the trigger Lambda, an (initially disabled) EventBridge schedule, and Redshift Serverless. Run `terraform destroy` when done - Redshift Serverless has no idle compute cost once destroyed, but there's no reason to leave any of this running between demos.

### Deployment evidence

*(Fill in after running `terraform apply` and triggering the pipeline once: Glue job run logs, a Redshift query result, and an AWS Cost Explorer screenshot showing the actual - small - cost of the run, then `terraform destroy`.)*

## Limitations

See the live site's "Limitations, Tested" tab for the full, current writeup. Summary:

- Only ~40% of facilities have a disclosed capacity (MW) - aggregate capacity figures are a floor, not a complete inventory.
- Census population is aggregated to the **block group** (not block) level and represented by each block group's **geometric centroid** (in an equal-area projection), not an official population-weighted center of population - verified correct in total (334,735,155, matching the official 2020 population exactly) but imprecise at the level of an individual large rural block group.
- The proximity metric counts a block group's *entire* population when its centroid falls within a radius, and none of it otherwise - a coarser approximation than areal-weighted population.
- Before/after imagery uses a single least-cloudy scene per window, not a cloud-free mosaic.

## Attribution

Facility data: [FracTracker Alliance National Data Centers Tracker](https://www.fractracker.org/map/national/data-centers/), used under their free non-commercial terms.
