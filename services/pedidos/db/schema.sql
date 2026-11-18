-- Orders service schema (PostgreSQL).
-- Idempotent: safe to run more than once. Run it inside one transaction
-- (psql --single-transaction), so this file has no BEGIN/COMMIT.
-- Needs the Products schema first (order_items references products).
-- No credentials, users or addresses belong in this file.

CREATE TABLE IF NOT EXISTS orders (
    id         UUID PRIMARY KEY,
    -- Reserved for the Cognito user (the "sub" claim). NULL = anonymous order.
    user_id    TEXT CHECK (user_id IS NULL OR length(user_id) BETWEEN 1 AND 128),
    total      NUMERIC(12,2) NOT NULL CHECK (total >= 0 AND total <= 1000000000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS order_items (
    order_id   UUID NOT NULL REFERENCES orders (id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products (id) ON DELETE RESTRICT,
    -- Name and price are copied at purchase time: later catalog changes must
    -- not rewrite past orders.
    name       TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    quantity   SMALLINT NOT NULL CHECK (quantity BETWEEN 1 AND 99),
    unit_price NUMERIC(10,2) NOT NULL CHECK (unit_price >= 0 AND unit_price <= 10000000),
    PRIMARY KEY (order_id, product_id)
);

CREATE INDEX IF NOT EXISTS orders_user_id_idx ON orders (user_id);

-- ---------------------------------------------------------------------------
-- Customer isolation. KEEP THIS BLOCK IDENTICAL to the one in migrate-rls.sql
-- (the migration for volumes created before it existed).
-- ---------------------------------------------------------------------------

-- New orders must belong to a customer. NOT VALID: rows that already exist
-- (the old anonymous orders, user_id NULL) are not checked; nobody can see them.
ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_user_required;
ALTER TABLE orders ADD CONSTRAINT orders_user_required
    CHECK (user_id IS NOT NULL) NOT VALID;

-- Row-level security. The service sets app.user_id (the verified Cognito sub)
-- inside each transaction; a role without BYPASSRLS that does not own the
-- tables only sees, and only inserts, rows of that customer. With app.user_id
-- unset or empty, nullif() gives NULL, the comparison is never true and no row
-- is visible. There are no UPDATE or DELETE policies: those stay denied.
-- Table owners and superusers bypass RLS (the admin role, not the service role).
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_items ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS orders_select_own ON orders;
CREATE POLICY orders_select_own ON orders FOR SELECT
    USING (user_id = nullif(current_setting('app.user_id', true), ''));

DROP POLICY IF EXISTS orders_insert_own ON orders;
CREATE POLICY orders_insert_own ON orders FOR INSERT
    WITH CHECK (user_id = nullif(current_setting('app.user_id', true), ''));

-- Lines are checked against the order's owner explicitly (not only through the
-- RLS of the orders table inside the sub-select).
DROP POLICY IF EXISTS order_items_select_own ON order_items;
CREATE POLICY order_items_select_own ON order_items FOR SELECT
    USING (EXISTS (
        SELECT 1 FROM orders o
        WHERE o.id = order_items.order_id
          AND o.user_id = nullif(current_setting('app.user_id', true), '')
    ));

DROP POLICY IF EXISTS order_items_insert_own ON order_items;
CREATE POLICY order_items_insert_own ON order_items FOR INSERT
    WITH CHECK (EXISTS (
        SELECT 1 FROM orders o
        WHERE o.id = order_items.order_id
          AND o.user_id = nullif(current_setting('app.user_id', true), '')
    ));
