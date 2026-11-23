# Remote state in S3, with a lock file next to it (use_lockfile, no DynamoDB).
# A backend block cannot use variables, so everything that changes between
# environments (bucket, endpoint, path style) lives in a local values file:
#   terraform init -backend-config=floci.tfbackend
# See floci.tfbackend.example. With Floci that file points to Floci; it never
# holds a real AWS endpoint. The state may hold secrets (the database master
# password): the bucket must be private, versioned and encrypted.
terraform {
  backend "s3" {
    key          = "estore/terraform.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}
