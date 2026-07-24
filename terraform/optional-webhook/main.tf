# OPTIONAL / DEFERRED — Phase D: Darwin webhook stage -> Lambda -> landing bucket.
# Apply as its own root module only if streaming sync is needed later;
# the primary sync path is the export-based notebook 02 run as a scheduled job.

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 5.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.4" }
  }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "aws_profile" {
  type    = string
  default = null
}

variable "name_prefix" {
  type    = string
  default = "v7-darwin-e2e"
}

variable "webhook_auth_token" {
  description = "Shared secret the Darwin webhook stage sends in the Authorization header"
  type        = string
  sensitive   = true
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "landing" {
  bucket        = "${var.name_prefix}-landing-${data.aws_caller_identity.current.account_id}"
  force_destroy = true
}

data "archive_file" "webhook" {
  type        = "zip"
  source_file = "${path.module}/lambda/webhook_handler.py"
  output_path = "${path.module}/lambda/webhook_handler.zip"
}

resource "aws_iam_role" "webhook" {
  name = "${var.name_prefix}-webhook-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "webhook" {
  name = "landing-write"
  role = aws_iam_role.webhook.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.landing.arn}/webhook/*"
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "*"
      },
    ]
  })
}

resource "aws_lambda_function" "webhook" {
  function_name    = "${var.name_prefix}-webhook"
  role             = aws_iam_role.webhook.arn
  runtime          = "python3.12"
  handler          = "webhook_handler.handler"
  filename         = data.archive_file.webhook.output_path
  source_code_hash = data.archive_file.webhook.output_base64sha256
  timeout          = 30

  environment {
    variables = {
      LANDING_BUCKET = aws_s3_bucket.landing.bucket
      AUTH_TOKEN     = var.webhook_auth_token
    }
  }
}

resource "aws_lambda_function_url" "webhook" {
  function_name      = aws_lambda_function.webhook.function_name
  authorization_type = "NONE" # auth enforced in-handler via the Authorization header
}

output "landing_bucket" {
  value = aws_s3_bucket.landing.bucket
}

output "webhook_url" {
  value = aws_lambda_function_url.webhook.function_url
}
