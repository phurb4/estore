# Customer identity (external users of the store). Customers sign up with their
# email, confirm it with a code and may turn on TOTP MFA from their profile.
# Tags come from the provider default_tags (see providers.tf).

locals {
  # Password rules. Customers are external, so the length is the main defence.
  password_minimum_length = 12

  # Token lifetimes. Short access/ID tokens, longer refresh token.
  access_token_minutes = 60
  id_token_minutes     = 60
  refresh_token_days   = 30
}

resource "aws_cognito_user_pool" "customers" {
  name = "${local.project}-customers"

  # The email address is the username, and it must be confirmed with a code
  # before the account is usable.
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  # Customers register themselves (no invitation by an administrator).
  admin_create_user_config {
    allow_admin_create_user_only = false
  }

  # MFA is optional: it only applies to customers who enable it in their
  # profile. TOTP (authenticator app) needs no SMS or email service.
  mfa_configuration = "OPTIONAL"
  software_token_mfa_configuration {
    enabled = true
  }

  password_policy {
    minimum_length                   = local.password_minimum_length
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 7
  }

  verification_message_template {
    default_email_option = "CONFIRM_WITH_CODE"
  }

  email_configuration {
    email_sending_account = "COGNITO_DEFAULT"
  }

  # Password recovery only through the verified email.
  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  depends_on = [terraform_data.account_guard]
}

# Public client: it runs in the browser, so it has no client secret.
resource "aws_cognito_user_pool_client" "web" {
  name         = "${local.project}-web"
  user_pool_id = aws_cognito_user_pool.customers.id

  generate_secret = false

  # SRP: the password never travels to Cognito; only a proof of it does.
  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  # Same answer whether or not an email is registered (no user enumeration).
  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true

  access_token_validity  = local.access_token_minutes
  id_token_validity      = local.id_token_minutes
  refresh_token_validity = local.refresh_token_days

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}

output "cognito_user_pool_id" {
  description = "Customer user pool ID (not a secret)."
  value       = aws_cognito_user_pool.customers.id
}

output "cognito_web_client_id" {
  description = "Browser app client ID (public, no secret)."
  value       = aws_cognito_user_pool_client.web.id
}
