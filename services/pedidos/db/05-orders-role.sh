#!/bin/bash
# Creates the role the Orders service connects with.
# Runs once, on first start with an empty data volume, after the Products
# schema/seed and the Orders schema (the tables must exist before the GRANT).
# Name and password come from the environment; nothing is written here.
# Least privilege: read products, insert orders. No UPDATE, DELETE or SELECT
# on the order tables.
set -e

: "${ORDERS_DB_USER:?Set ORDERS_DB_USER}"
: "${ORDERS_DB_PASSWORD:?Set ORDERS_DB_PASSWORD}"

# psql variables (:"role" as identifier, :'pw' as literal) quote the values
# safely. The heredoc is quoted so the shell does not expand anything in it.
psql -v ON_ERROR_STOP=1 \
     -v role="$ORDERS_DB_USER" -v pw="$ORDERS_DB_PASSWORD" \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'EOSQL'
CREATE ROLE :"role" LOGIN PASSWORD :'pw'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
GRANT CONNECT ON DATABASE :"DBNAME" TO :"role";
GRANT USAGE ON SCHEMA public TO :"role";
GRANT SELECT ON public.products TO :"role";
GRANT INSERT ON public.orders, public.order_items TO :"role";
EOSQL
