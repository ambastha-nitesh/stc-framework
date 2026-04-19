output "bucket_name" { value = aws_s3_bucket.audit.bucket }
output "bucket_arn" { value = aws_s3_bucket.audit.arn }
output "bucket_regional_domain_name" { value = aws_s3_bucket.audit.bucket_regional_domain_name }
