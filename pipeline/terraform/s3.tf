# Single bucket, prefix-partitioned by pipeline stage. One bucket instead of
# several keeps the IAM policies and lifecycle rules in one place - real
# data volume here (facilities CSV, census parquet, a handful of imagery
# COGs) doesn't need bucket-level isolation.
resource "aws_s3_bucket" "data" {
  bucket = "${var.project_name}-${var.environment}-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Glue job scripts live under scripts/, referenced by the Glue job resource.
resource "aws_s3_object" "clean_facilities_script" {
  bucket = aws_s3_bucket.data.id
  key    = "scripts/clean_facilities.py"
  source = "${path.module}/../glue/clean_facilities.py"
  etag   = filemd5("${path.module}/../glue/clean_facilities.py")
}

data "aws_caller_identity" "current" {}
