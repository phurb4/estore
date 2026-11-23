# Spending alarm: one monthly cost budget with an email at 80% of the limit
# (actual spend) and at 100% (forecast). It only warns; it does not stop anything.
# Tags come from the provider default_tags (see providers.tf).

resource "aws_budgets_budget" "monthly" {
  # Explicit: with the emulator the provider skips the account lookup.
  account_id   = data.aws_caller_identity.current.account_id
  name         = "${local.project}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = var.budget_alert_emails
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = var.budget_alert_emails
  }

  depends_on = [terraform_data.account_guard]
}
