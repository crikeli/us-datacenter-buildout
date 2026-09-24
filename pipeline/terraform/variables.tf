variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Short name used as a prefix for every resource"
  type        = string
  default     = "us-dc-buildout"
}

variable "environment" {
  description = "Deployment environment tag"
  type        = string
  default     = "demo"
}

variable "redshift_admin_username" {
  description = "Admin username for the Redshift Serverless namespace"
  type        = string
  default     = "admin"
}

variable "redshift_admin_password" {
  description = "Admin password for the Redshift Serverless namespace. Passed via TF_VAR_redshift_admin_password, never committed."
  type        = string
  sensitive   = true
}

variable "redshift_base_capacity" {
  description = "Redshift Serverless base RPU capacity (8 is the minimum)"
  type        = number
  default     = 8
}
