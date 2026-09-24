resource "aws_glue_catalog_database" "facilities" {
  name = "${replace(var.project_name, "-", "_")}_facilities"
}

# Same clean_facilities.py proven locally against the real FracTracker CSV
# (see pipeline/glue/clean_facilities.py) - only the --input/--output paths
# change here, to S3 locations, via --input-path/--output-path job args.
resource "aws_glue_job" "clean_facilities" {
  name              = "${var.project_name}-clean-facilities"
  role_arn          = aws_iam_role.glue_job.arn
  glue_version      = "4.0"
  worker_type       = "G.1X"
  number_of_workers = 2
  timeout           = 30

  command {
    name            = "glueetl"
    script_location = "s3://${aws_s3_bucket.data.id}/${aws_s3_object.clean_facilities_script.key}"
    python_version  = "3"
  }

  default_arguments = {
    "--input"                            = "s3://${aws_s3_bucket.data.id}/raw/fractracker_raw.csv"
    "--output"                           = "s3://${aws_s3_bucket.data.id}/clean/facilities_clean.parquet"
    "--job-language"                     = "python"
    "--enable-metrics"                   = "true"
    "--enable-continuous-cloudwatch-log" = "true"
    "--TempDir"                          = "s3://${aws_s3_bucket.data.id}/glue-temp/"
  }
}

resource "aws_glue_crawler" "facilities_clean" {
  name          = "${var.project_name}-facilities-clean-crawler"
  role          = aws_iam_role.glue_job.arn
  database_name = aws_glue_catalog_database.facilities.name

  s3_target {
    path = "s3://${aws_s3_bucket.data.id}/clean/"
  }
}
