"""
Orchestrates the real local pipeline (the same scripts run manually and
verified while building this project) as an Airflow DAG. Runs locally at
zero cost - each task is one of the scripts under pipeline/glue or
pipeline/prep, called with the same local file paths used to produce this
project's actual results.

MWAA note: to deploy this to Amazon MWAA instead of running locally,
change PROJECT_ROOT to an S3-backed mount (or S3ToLocalFilesystemOperator
tasks ahead of each step) and swap the PySpark step to a GlueOperator /
Step Functions trigger, since MWAA's workers aren't a Spark environment -
see pipeline/terraform/step_functions.tf for that equivalent orchestration
already written for the real AWS deployment.

Usage (syntax/import check only, no scheduler/webserver needed):
    python -c "from datacenter_buildout_dag import dag; print(dag.task_dict)"
"""

from datetime import datetime
from pathlib import Path

from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
PYTHON = "python3"  # run inside the us-datacenter-buildout conda env

with DAG(
    dag_id="us_datacenter_buildout",
    description="Clean FracTracker data, join real Census population, run proximity analysis, pull before/after imagery, export dashboard data.",
    schedule=None,  # triggered manually / by the equivalent EventBridge rule in AWS - see pipeline/terraform/eventbridge.tf
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["us-datacenter-buildout"],
) as dag:

    clean_facilities = BashOperator(
        task_id="clean_facilities",
        bash_command=(
            f"cd {PROJECT_ROOT}/pipeline/glue && {PYTHON} clean_facilities.py "
            f"--input {DATA_DIR}/fractracker_raw.csv "
            f"--output {DATA_DIR}/facilities_clean.parquet"
        ),
    )

    build_census_population = BashOperator(
        task_id="build_census_population",
        bash_command=(
            f"cd {PROJECT_ROOT}/pipeline/prep && {PYTHON} build_census_population.py "
            f"--population-dir {DATA_DIR}/census_raw/population_parts "
            f"--block-groups {DATA_DIR}/census_raw/cb_2020_us_bg_500k.parquet "
            f"--output {DATA_DIR}/census_bg_population.parquet"
        ),
    )

    build_proximity_analysis = BashOperator(
        task_id="build_proximity_analysis",
        bash_command=(
            f"cd {PROJECT_ROOT}/pipeline/prep && {PYTHON} build_proximity_analysis.py "
            f"--facilities {DATA_DIR}/facilities_clean.parquet "
            f"--population {DATA_DIR}/census_bg_population_flat.parquet "
            f"--output {DATA_DIR}/facility_proximity.parquet"
        ),
    )

    build_imagery_candidates = BashOperator(
        task_id="build_imagery_candidates",
        bash_command=(
            f"cd {PROJECT_ROOT}/pipeline/prep && {PYTHON} build_imagery_candidates.py "
            f"--facilities {DATA_DIR}/facility_proximity.parquet "
            f"--output {DATA_DIR}/imagery_candidates.csv "
            f"--top-n 9"
        ),
    )

    build_before_after_imagery = BashOperator(
        task_id="build_before_after_imagery",
        bash_command=(
            f"cd {PROJECT_ROOT}/pipeline/prep && {PYTHON} build_before_after_imagery.py "
            f"--candidates {DATA_DIR}/imagery_candidates.csv "
            f"--output-dir {DATA_DIR}/imagery"
        ),
    )

    build_docs_data = BashOperator(
        task_id="build_docs_data",
        bash_command=(
            f"cd {PROJECT_ROOT}/pipeline/prep && {PYTHON} build_docs_data.py "
            f"--facilities {DATA_DIR}/facility_proximity.parquet "
            f"--imagery-dir {DATA_DIR}/imagery "
            f"--docs-dir {PROJECT_ROOT}/docs"
        ),
    )

    # clean_facilities and build_census_population are independent (neither
    # reads the other's output) - both feed build_proximity_analysis, which
    # needs both real datasets joined.
    [clean_facilities, build_census_population] >> build_proximity_analysis
    build_proximity_analysis >> build_imagery_candidates >> build_before_after_imagery >> build_docs_data
