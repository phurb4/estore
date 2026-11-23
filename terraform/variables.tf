variable "environment" {
  description = "Environment name, used in tags (for example floci or aws)."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9-]{1,20}$", var.environment))
    error_message = "environment must be 1-20 characters: lowercase letters, digits and hyphens."
  }
}

variable "aws_region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "aws_endpoint_url" {
  description = "Emulator address (Floci). Leave null for real AWS."
  type        = string
  default     = null
}

variable "expected_account_id" {
  description = "12-digit account this environment must run against. Terraform stops if the account in use is different (protection against hitting the wrong account)."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "expected_account_id must be exactly 12 digits."
  }
}

variable "db_engine_version" {
  description = "PostgreSQL major version for RDS."
  type        = string
  default     = "18"
}

variable "db_instance_class" {
  description = "RDS instance size."
  type        = string
  default     = "db.t4g.micro"
}

variable "state_bucket_name" {
  description = "Name of the S3 bucket that holds the Terraform state (the same value as bucket in the .tfbackend file; a backend block cannot read variables, so it is repeated here for the IAM policy)."
  type        = string
}

variable "state_key" {
  description = "Object key of the state file (must match key in backend.tf)."
  type        = string
  default     = "estore/terraform.tfstate"
}

variable "db_subnet_group_name" {
  description = "Name of an existing DB subnet group (private subnets). Optional only for the emulator; REQUIRED on real AWS, otherwise RDS lands in the default VPC."
  type        = string
  default     = null
}

variable "db_security_group_ids" {
  description = "Security group IDs for the database (allow 5432 only from the services). Optional only for the emulator; REQUIRED on real AWS, otherwise the default security group is used."
  type        = list(string)
  default     = null
}

variable "protect_database" {
  description = "true on real AWS: deletion protection on and a final snapshot on destroy. false only for the emulator."
  type        = bool
  default     = true
}

variable "secret_recovery_days" {
  description = "Days a deleted secret stays recoverable: 0 (delete at once, emulator only) or 7 to 30."
  type        = number
  default     = 7

  validation {
    condition     = var.secret_recovery_days == 0 || (var.secret_recovery_days >= 7 && var.secret_recovery_days <= 30)
    error_message = "secret_recovery_days must be 0 or between 7 and 30."
  }
}

variable "budget_limit_usd" {
  description = "Monthly cost limit in USD for the budget alarm."
  type        = number
  default     = 10

  validation {
    condition     = var.budget_limit_usd > 0
    error_message = "budget_limit_usd must be greater than 0."
  }
}

variable "budget_alert_emails" {
  description = "Addresses that receive the budget alarms. Set them in the values file of each environment."
  type        = list(string)

  validation {
    condition     = length(var.budget_alert_emails) > 0
    error_message = "Give at least one address in budget_alert_emails."
  }
}

variable "force_delete_repositories" {
  description = "Allow destroying image repositories that still contain images. Only for the emulator."
  type        = bool
  default     = false
}
