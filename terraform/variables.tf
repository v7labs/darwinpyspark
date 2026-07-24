variable "aws_region" {
  description = "Region for the PoC buckets (US on purpose, mimicking GEHC residency)"
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "AWS CLI profile for the dev account"
  type        = string
  default     = null
}

variable "name_prefix" {
  description = "Prefix for all resources"
  type        = string
  default     = "v7-darwin-e2e"
}

variable "v7_external_role_arn" {
  description = <<-EOT
    The IAM role V7 Darwin assumes to presign requests against external-storage
    buckets. The default is Darwin's production role (see
    https://docs.v7labs.com/docs/aws-s3-configuration). Cross-check against the
    ARN shown in the storage-integration setup UI when creating the integration.
  EOT
  type        = string
  default     = "arn:aws:iam::258327614892:role/external_s3"
}

variable "darwin_origin" {
  description = "Darwin web origin for bucket CORS (your Darwin environment URL)"
  type        = string
  default     = "https://darwin.v7labs.com"
}

variable "readonly" {
  description = "If true, grant V7 GetObject only (read-only storage mode); otherwise Get+Put"
  type        = bool
  default     = false
}
