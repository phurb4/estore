output "account_id" {
  description = "Account Terraform is working against (check it is the expected one)."
  value       = data.aws_caller_identity.current.account_id
}

output "repository_urls" {
  description = "Image repository address of each service."
  value       = { for name, repo in aws_ecr_repository.service : name => repo.repository_url }
}

output "pod_identity_role_arns" {
  description = "IAM role of each service for EKS Pod Identity."
  value       = { for name, role in aws_iam_role.pod_identity : name => role.arn }
}
