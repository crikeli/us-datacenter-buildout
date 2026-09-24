data "archive_file" "trigger_pipeline" {
  type        = "zip"
  source_file = "${path.module}/../lambda/trigger_pipeline.py"
  output_path = "${path.module}/../lambda/trigger_pipeline.zip"
}

resource "aws_lambda_function" "trigger_pipeline" {
  function_name    = "${var.project_name}-trigger-pipeline"
  role             = aws_iam_role.lambda.arn
  handler          = "trigger_pipeline.handler"
  runtime          = "python3.12"
  timeout          = 30
  filename         = data.archive_file.trigger_pipeline.output_path
  source_code_hash = data.archive_file.trigger_pipeline.output_base64sha256

  environment {
    variables = {
      STATE_MACHINE_ARN = aws_sfn_state_machine.pipeline.arn
    }
  }
}
