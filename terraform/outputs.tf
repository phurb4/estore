output "account_id" {
  description = "Account Terraform is working against (check it is the expected one)."
  value       = data.aws_caller_identity.current.account_id
}

output "repository_urls" {
  description = "Image repository address of each service."
  value       = { for name, repo in aws_ecr_repository.service : name => repo.repository_url }
}
