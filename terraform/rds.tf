# PostgreSQL for the catalog and the orders (Amazon RDS). In Floci the API
# answers, but a real database engine only starts if Floci can reach the Docker
# socket, which this project does not mount (see docker-compose.yml). The local
# database for development is the "db" service of Compose.
# Tags come from the provider default_tags (see providers.tf).

# The master password is generated here and never written in the code. It ends
# up in the Terraform state, so the state must stay private (see backend.tf).
resource "random_password" "db_master" {
  length  = 32
  special = false
}

resource "aws_db_instance" "main" {
  identifier = "${local.project}-db"

  engine         = "postgres"
  engine_version = var.db_engine_version
  instance_class = var.db_instance_class

  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = "estore"
  username = "estore_admin"
  password = random_password.db_master.result

  # Never reachable from the Internet; services reach it from inside the VPC.
  publicly_accessible = false
  multi_az            = false

  iam_database_authentication_enabled = true
  auto_minor_version_upgrade          = true
  backup_retention_period             = 1
  copy_tags_to_snapshot               = true

  # The emulator may be destroyed freely; real AWS must not lose the data.
  deletion_protection = var.protect_database
  skip_final_snapshot = !var.protect_database

  depends_on = [terraform_data.account_guard]
}
