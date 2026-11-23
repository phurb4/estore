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
  # Exact actions the Terraform AWS provider calls for the resources of this
  # project (no service wildcards), on the project's ARNs where the service
  # allows it.
  statement {
    sid = "ManageProjectRepositories"
    actions = [
      "ecr:CreateRepository",
      "ecr:DeleteRepository",
      "ecr:DescribeRepositories",
      "ecr:ListTagsForResource",
      "ecr:TagResource",
      "ecr:UntagResource",
      "ecr:PutImageScanningConfiguration",
      "ecr:PutImageTagMutability",
    ]
    resources = ["arn:aws:ecr:${var.aws_region}:${data.aws_caller_identity.current.account_id}:repository/${local.project}/*"]
  }

  # Cannot be narrowed: the user pool ID does not exist before creation, and
  # CreateUserPool has no resource-level permission.
  statement {
    sid = "ManageUserPools"
    actions = [
      "cognito-idp:CreateUserPool",
      "cognito-idp:DeleteUserPool",
      "cognito-idp:DescribeUserPool",
      "cognito-idp:UpdateUserPool",
      "cognito-idp:SetUserPoolMfaConfig",
      "cognito-idp:GetUserPoolMfaConfig",
      "cognito-idp:CreateUserPoolClient",
      "cognito-idp:DescribeUserPoolClient",
      "cognito-idp:UpdateUserPoolClient",
      "cognito-idp:DeleteUserPoolClient",
      "cognito-idp:ListTagsForResource",
      "cognito-idp:TagResource",
      "cognito-idp:UntagResource",
    ]
    resources = ["*"]
  }

  statement {
    sid = "ManageDatabaseInstance"
    actions = [
      "rds:CreateDBInstance",
      "rds:ModifyDBInstance",
      "rds:DeleteDBInstance",
      "rds:AddTagsToResource",
      "rds:RemoveTagsFromResource",
      "rds:ListTagsForResource",
    ]
    resources = ["arn:aws:rds:${var.aws_region}:${data.aws_caller_identity.current.account_id}:db:${local.project}-*"]
  }

  # Describe* does not support a narrower resource; CreateDBInstance also needs
  # access to the subnet group that is passed in (any name in the account).
  statement {
    sid       = "DescribeDatabases"
    actions   = ["rds:DescribeDBInstances"]
    resources = ["*"]
  }

  statement {
    sid       = "UseDatabaseNetwork"
    actions   = ["rds:CreateDBInstance", "rds:ModifyDBInstance"]
    resources = ["arn:aws:rds:${var.aws_region}:${data.aws_caller_identity.current.account_id}:subgrp:*"]
  }

  statement {
    sid = "ManageBudget"
    actions = [
      "budgets:ViewBudget",
      "budgets:ModifyBudget",
      "budgets:DeleteBudget",
      "budgets:ListTagsForResource",
      "budgets:TagResource",
      "budgets:UntagResource",
    ]
    resources = ["arn:aws:budgets::${data.aws_caller_identity.current.account_id}:budget/${local.project}-*"]
  }

  # Creating a budget has no resource-level scoping that works before it exists.
  statement {
    sid       = "CreateBudget"
    actions   = ["budgets:CreateBudget"]
    resources = ["*"]
  }

  # Only the secrets of this project. The ARN ends with a random suffix.
  statement {
    sid = "ManageProjectSecrets"
    actions = [
      "secretsmanager:CreateSecret",
      "secretsmanager:DeleteSecret",
      "secretsmanager:DescribeSecret",
      "secretsmanager:UpdateSecret",
      "secretsmanager:PutSecretValue",
      "secretsmanager:GetSecretValue",
      "secretsmanager:GetResourcePolicy",
      "secretsmanager:TagResource",
      "secretsmanager:UntagResource",
    ]
    resources = ["arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${local.project}/*"]
  }

  # Remote state (backend.tf, use_lockfile): list the bucket, and read, write
  # and delete only the state object and its lock file. No s3:*.
  statement {
    sid       = "ListStateBucket"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.state_bucket_name}"]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${local.project}/*"]
    }
  }

  # The state object is only read and written; Terraform never deletes it.
  statement {
    sid       = "UseStateObject"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["arn:aws:s3:::${var.state_bucket_name}/${var.state_key}"]
  }

  # The lock file is created and removed on every run.
  statement {
    sid       = "UseStateLockFile"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["arn:aws:s3:::${var.state_bucket_name}/${var.state_key}.tflock"]
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
