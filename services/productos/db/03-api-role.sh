#!/bin/bash
# Creates the read-only role the Products API connects with.
# Runs once, on first start with an empty data volume, after 01-schema.sql
# and 02-seed.sql (the tables must exist before the GRANT).
# Name and password come from the environment; nothing is written here.
set -e

: "${API_DB_USER:?Set API_DB_USER}"
: "${API_DB_PASSWORD:?Set API_DB_PASSWORD}"

# psql variables (:"role" as identifier, :'pw' as literal) quote the values
# safely. The heredoc is quoted so the shell does not expand anything in it.
psql -v ON_ERROR_STOP=1 \
     -v role="$API_DB_USER" -v pw="$API_DB_PASSWORD" \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'EOSQL'
CREATE ROLE :"role" LOGIN PASSWORD :'pw'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
ALTER ROLE :"role" SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE :"DBNAME" TO :"role";
GRANT USAGE ON SCHEMA public TO :"role";
GRANT SELECT ON public.categories, public.products TO :"role";
EOSQL
