# EKS Pod Identity: one IAM role per service, so each pod reads only its own
# database secret (no node role, no shared role). The Pod Identity agent of the
# cluster hands the role's temporary credentials to the pods of the service
# account named in the association (fixed namespace + service account).
#   productos -> secret estore/db/api
#   pedidos   -> secret estore/db/orders
# The role never gets a wildcard: the resource is the full ARN of its own
# secret (Terraform attribute, including the random suffix AWS adds).
# The associations need an existing EKS cluster; with eks_cluster_name unset
# (emulator) only the roles are created. Tags come from the provider
# default_tags (see providers.tf) plus the Service tag below.

locals {
  pod_identity_services = {
    productos = { secret_key = "api", service_account = "productos" }
    pedidos   = { secret_key = "orders", service_account = "pedidos" }
  }
}

data "aws_iam_policy_document" "trust_pod_identity" {
  statement {
    sid     = "AllowEksPodIdentity"
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
    # Confused-deputy guard: only pods of this account.
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "pod_identity" {
  for_each = local.pod_identity_services

  name                 = "${local.project}-pod-${each.key}"
  description          = "EKS Pod Identity role of the ${each.key} service: reads its own database secret."
  assume_role_policy   = data.aws_iam_policy_document.trust_pod_identity.json
  max_session_duration = 3600

  tags = { Service = each.key }

  depends_on = [terraform_data.account_guard]
}

data "aws_iam_policy_document" "pod_identity_secret" {
  for_each = local.pod_identity_services

  statement {
    sid     = "ReadOwnDatabaseSecret"
    actions = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    # Full ARN of this service's secret only. No wildcard.
    resources = [aws_secretsmanager_secret.db[each.value.secret_key].arn]
  }
}

resource "aws_iam_role_policy" "pod_identity_secret" {
  for_each = local.pod_identity_services

  name   = "read-own-db-secret"
  role   = aws_iam_role.pod_identity[each.key].id
  policy = data.aws_iam_policy_document.pod_identity_secret[each.key].json

  depends_on = [terraform_data.account_guard]
}

# Namespace and service account are fixed (they match k8s/namespace.yaml and
# the ServiceAccount of each service).
resource "aws_eks_pod_identity_association" "service" {
  for_each = var.eks_cluster_name == null ? {} : local.pod_identity_services

  cluster_name    = var.eks_cluster_name
  namespace       = var.k8s_namespace
  service_account = each.value.service_account
  role_arn        = aws_iam_role.pod_identity[each.key].arn

  tags = { Service = each.key }

  depends_on = [terraform_data.account_guard]
}
