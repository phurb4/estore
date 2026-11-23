# Two roles, both assumed with sts:AssumeRole (nobody works as the account root):
#  - readonly: permanent, can only look at things.
#  - admin-temporary: more privileges, for one-off changes. Needs MFA, and its
#    session is the shortest AWS allows (1 hour).
# Neither is AdministratorAccess: each policy lists only the services this
# project uses. Tags come from the provider default_tags (see providers.tf).

locals {
  # Who may assume the roles: identities of this same account that also hold
  # the sts:AssumeRole permission.
  trusted_principal = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
}

data "aws_iam_policy_document" "trust_readonly" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = [local.trusted_principal]
    }
  }
}

data "aws_iam_policy_document" "trust_admin" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = [local.trusted_principal]
    }
    # No MFA, no role.
    condition {
      test     = "Bool"
      variable = "aws:MultiFactorAuthPresent"
      values   = ["true"]
    }
  }
}

# Read-only: Describe/List/Get on the services of the project, nothing else.
data "aws_iam_policy_document" "readonly" {
  statement {
    sid = "ReadProjectServices"
    actions = [
      "ecr:Describe*",
      "ecr:List*",
      "ecr:GetRepositoryPolicy",
      "cognito-idp:Describe*",
      "cognito-idp:List*",
      "cognito-idp:GetUserPoolMfaConfig",
      "rds:Describe*",
      "rds:ListTagsForResource",
      "budgets:ViewBudget",
      "iam:GetRole",
      "iam:ListRoles",
      "iam:ListAttachedRolePolicies",
      "iam:ListRolePolicies",
    ]
    resources = ["*"]
  }
}

# Higher privilege, still scoped: manage what Terraform manages. No IAM user
# management, no access to billing, nothing outside these services.
data "aws_iam_policy_document" "admin_temporary" {
  statement {
    sid = "ManageProjectServices"
    actions = [
      "ecr:*",
      "cognito-idp:*",
      "rds:*",
      "budgets:*",
      "secretsmanager:*",
    ]
    resources = ["*"]
  }

  # Roles of this project: READ ONLY. No iam write action on purpose: with
  # iam:PutRolePolicy on role/estore-* (which includes this very role) the role
  # could grant itself administrator rights. IAM changes go through a reviewed
  # terraform apply, not through this role.
  statement {
    sid = "ReadProjectRoles"
    actions = [
      "iam:GetRole",
      "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies",
      "iam:GetRolePolicy",
    ]
    resources = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.project}-*"]
  }
}

resource "aws_iam_role" "readonly" {
  name                 = "${local.project}-readonly"
  description          = "Permanent read-only access to the eStore resources."
  assume_role_policy   = data.aws_iam_policy_document.trust_readonly.json
  max_session_duration = 3600

  depends_on = [terraform_data.account_guard]
}

resource "aws_iam_role_policy" "readonly" {
  name   = "read-project-services"
  role   = aws_iam_role.readonly.id
  policy = data.aws_iam_policy_document.readonly.json

  depends_on = [terraform_data.account_guard]
}

resource "aws_iam_role" "admin_temporary" {
  name                 = "${local.project}-admin-temporary"
  description          = "Elevated, short-lived access for one-off changes. Requires MFA."
  assume_role_policy   = data.aws_iam_policy_document.trust_admin.json
  max_session_duration = 3600

  depends_on = [terraform_data.account_guard]
}

resource "aws_iam_role_policy" "admin_temporary" {
  name   = "manage-project-services"
  role   = aws_iam_role.admin_temporary.id
  policy = data.aws_iam_policy_document.admin_temporary.json

  depends_on = [terraform_data.account_guard]
}
