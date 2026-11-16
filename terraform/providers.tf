terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

# One configuration for every environment. The environment is chosen by the
# values file passed with -var-file (see floci.tfvars.example).
#  - Emulator (Floci): aws_endpoint_url is set, so every service listed below
#    is sent to the emulator and nothing reaches a real AWS account.
#  - Real AWS: aws_endpoint_url stays null, the endpoints block disappears and
#    the provider uses the official AWS endpoints.
# Credentials are never written here: they come from the AWS_PROFILE
# environment variable (one AWS CLI profile per environment).
#
# An endpoint must be listed for EVERY service this configuration uses. When
# you add a resource of a new service, add its endpoint here too.
locals {
  use_emulator = var.aws_endpoint_url != null
}

provider "aws" {
  region = var.aws_region

  # These checks need the real AWS identity service; they are skipped only
  # for the emulator.
  skip_credentials_validation = local.use_emulator
  skip_metadata_api_check     = local.use_emulator
  skip_requesting_account_id  = local.use_emulator
  s3_use_path_style           = local.use_emulator

  default_tags {
    tags = local.common_tags
  }

  dynamic "endpoints" {
    for_each = local.use_emulator ? [var.aws_endpoint_url] : []
    content {
      cognitoidp = endpoints.value
      ecr        = endpoints.value
      sts        = endpoints.value
    }
  }
}
