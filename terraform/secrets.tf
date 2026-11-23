# Database credentials live in AWS Secrets Manager, not in environment
# variables. Each secret is JSON: {"username": "...", "password": "..."}.
# The services read it at start-up (DB_SECRET_ID) and need only
# secretsmanager:GetSecretValue on their own secret (policies below).
# Passwords are generated here and never written in the code; they end up in
# the Terraform state, so the state bucket must stay private (see backend.tf).
# Tags come from the provider default_tags (see providers.tf).

locals {
  db_secrets = {
    master = { name = "${local.project}/db/master", username = "estore_admin", password = random_password.db_master.result }
    api    = { name = "${local.project}/db/api", username = "estore_api", password = random_password.db_api.result }
    orders = { name = "${local.project}/db/orders", username = "estore_orders", password = random_password.db_orders.result }
  }
}

resource "random_password" "db_api" {
  length  = 32
  special = false
}

resource "random_password" "db_orders" {
  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "db" {
  for_each = local.db_secrets

  name        = each.value.name
  description = "PostgreSQL credentials (${each.key})."
  # 0 = delete at once (emulator only); real AWS keeps it recoverable.
  recovery_window_in_days = var.secret_recovery_days

  depends_on = [terraform_data.account_guard]
}

resource "aws_secretsmanager_secret_version" "db" {
  for_each = local.db_secrets

  secret_id = aws_secretsmanager_secret.db[each.key].id
  secret_string = jsonencode({
    username = each.value.username
    password = each.value.password
  })

  depends_on = [terraform_data.account_guard]
}

# One read-only policy per service: it can read its own secret and nothing else.
# Attach each one to the identity that runs that service.
data "aws_iam_policy_document" "read_secret" {
  for_each = toset(["api", "orders"])

  statement {
    sid       = "ReadOwnDatabaseSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.db[each.key].arn]
  }
}

resource "aws_iam_policy" "read_secret" {
  for_each = data.aws_iam_policy_document.read_secret

  name        = "${local.project}-read-db-secret-${each.key}"
  description = "Read the ${each.key} database secret only."
  policy      = each.value.json

  depends_on = [terraform_data.account_guard]
}
