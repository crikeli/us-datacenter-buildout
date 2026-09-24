# Optional recurring trigger, disabled by default. This project's own real
# results were produced by a single manual invocation of the Lambda, not a
# schedule - enable this only if re-running the pipeline periodically
# against FracTracker's live tracker is actually wanted.
resource "aws_cloudwatch_event_rule" "monthly_refresh" {
  name                = "${var.project_name}-monthly-refresh"
  schedule_expression = "rate(30 days)"
  state               = "DISABLED"
}

resource "aws_cloudwatch_event_target" "trigger_lambda" {
  rule = aws_cloudwatch_event_rule.monthly_refresh.name
  arn  = aws_lambda_function.trigger_pipeline.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.trigger_pipeline.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.monthly_refresh.arn
}
