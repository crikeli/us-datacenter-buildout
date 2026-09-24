output "data_bucket" {
  value = aws_s3_bucket.data.id
}

output "glue_job_name" {
  value = aws_glue_job.clean_facilities.name
}

output "state_machine_arn" {
  value = aws_sfn_state_machine.pipeline.arn
}

output "trigger_lambda_name" {
  value = aws_lambda_function.trigger_pipeline.function_name
}

output "redshift_workgroup" {
  value = aws_redshiftserverless_workgroup.main.workgroup_name
}
