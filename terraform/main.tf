locals {
  project = "estore"

  # Applied by the provider to every resource that supports tags.
  common_tags = {
    Project     = local.project
    Environment = var.environment
    ManagedBy   = "terraform"
  }

  # One private image repository per container image of the project.
  services = toset(["frontend", "pedidos", "productos"])
}

# Which account are we really talking to? If the endpoint configuration is
# wrong, this returns a different account and the guard below stops Terraform.
data "aws_caller_identity" "current" {}

resource "terraform_data" "account_guard" {
  lifecycle {
    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.expected_account_id
      error_message = "Wrong AWS account: the account in use is not the one in expected_account_id. Check AWS_PROFILE and aws_endpoint_url before continuing."
    }
  }
}

# Private registry for the images (the Compose images are not pushed as-is).
# Immutable tags: a published version can never be overwritten.
resource "aws_ecr_repository" "service" {
  for_each = local.services

  name                 = "${local.project}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = var.force_delete_repositories

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  depends_on = [terraform_data.account_guard]
}
