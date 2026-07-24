data "aws_caller_identity" "current" {}

locals {
  v7_s3_actions = var.readonly ? ["s3:GetObject"] : ["s3:GetObject", "s3:PutObject"]
}

# ------------------------------------------------------------------
# Customer-managed KMS key (the GEHC-shaped requirement)
# ------------------------------------------------------------------

resource "aws_kms_key" "source" {
  description = "${var.name_prefix} source-bucket CMK (V7 external storage PoC)"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AccountRoot"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        # This statement IS the copy-paste answer to GEHC's KMS question
        Sid       = "V7DarwinExternalStorage"
        Effect    = "Allow"
        Principal = { AWS = var.v7_external_role_arn }
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:DescribeKey",
        ]
        Resource = "*"
      },
    ]
  })
}

resource "aws_kms_alias" "source" {
  name          = "alias/${var.name_prefix}-source"
  target_key_id = aws_kms_key.source.key_id
}

# ------------------------------------------------------------------
# Source bucket: Databricks external location + V7 external storage
# NOTE: no dots in bucket names (V7 requirement)
# ------------------------------------------------------------------

resource "aws_s3_bucket" "source" {
  bucket        = "${var.name_prefix}-source-${data.aws_caller_identity.current.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "source" {
  bucket = aws_s3_bucket.source.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.source.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_policy" "source" {
  bucket = aws_s3_bucket.source.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DarwinAccess"
        Effect    = "Allow"
        Principal = { AWS = var.v7_external_role_arn }
        Action    = local.v7_s3_actions
        Resource  = "${aws_s3_bucket.source.arn}/*"
      },
      {
        # Needed for MIRAX and harmless otherwise
        Sid       = "DarwinList"
        Effect    = "Allow"
        Principal = { AWS = var.v7_external_role_arn }
        Action    = ["s3:ListBucket"]
        Resource  = aws_s3_bucket.source.arn
      },
    ]
  })
}

resource "aws_s3_bucket_cors_configuration" "source" {
  bucket = aws_s3_bucket.source.id
  cors_rule {
    allowed_origins = [var.darwin_origin]
    allowed_methods = ["GET", "HEAD"]
    allowed_headers = ["*"]
    max_age_seconds = 3000
  }
}

# Phase D (webhook stage -> Lambda -> landing bucket) is DEFERRED.
# When needed, apply terraform/optional-webhook/ as a separate root module.
