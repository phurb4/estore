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

variable "force_delete_repositories" {
  description = "Allow destroying image repositories that still contain images. Only for the emulator."
  type        = bool
  default     = false
}
