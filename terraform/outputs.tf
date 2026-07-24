output "source_bucket" {
  value       = aws_s3_bucket.source.bucket
  description = "Point both the Databricks external location and the Darwin storage integration here"
}

output "kms_key_arn" {
  value = aws_kms_key.source.arn
}
