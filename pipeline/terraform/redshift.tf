# Redshift Serverless, not a provisioned cluster: it scales to zero between
# queries instead of billing for an always-on node, which matters here
# since this infrastructure runs once to produce real results and is then
# torn down (see README) rather than left running permanently.
resource "aws_redshiftserverless_namespace" "main" {
  namespace_name       = "${var.project_name}-ns"
  admin_username       = var.redshift_admin_username
  admin_user_password  = var.redshift_admin_password
  db_name              = "datacenters"
  iam_roles            = [aws_iam_role.redshift.arn]
  default_iam_role_arn = aws_iam_role.redshift.arn
}

resource "aws_redshiftserverless_workgroup" "main" {
  namespace_name      = aws_redshiftserverless_namespace.main.namespace_name
  workgroup_name      = "${var.project_name}-wg"
  base_capacity       = var.redshift_base_capacity
  publicly_accessible = false
}
