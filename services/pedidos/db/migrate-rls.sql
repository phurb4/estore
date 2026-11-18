-- One-time migration for a database created BEFORE row-level security existed.
-- New volumes do not need it: schema.sql and 05-orders-role.sh already do this.
--
-- Run as the admin role, with the Orders role name as the psql variable "role":
--   psql -v ON_ERROR_STOP=1 -v role=<orders role> -U <admin> -d <db> -f migrate-rls.sql
-- Idempotent: running it again changes nothing. Everything happens in ONE
-- transaction: RLS and its policies are in place before the role gets SELECT,
-- and if any statement fails nothing is applied.
-- No names, passwords or addresses belong in this file.

BEGIN;

-- ---- same block as schema.sql ---------------------------------------------
ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_user_required;
ALTER TABLE orders ADD CONSTRAINT orders_user_required
    CHECK (user_id IS NOT NULL) NOT VALID;

ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_items ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS orders_select_own ON orders;
CREATE POLICY orders_select_own ON orders FOR SELECT
    USING (user_id = nullif(current_setting('app.user_id', true), ''));

DROP POLICY IF EXISTS orders_insert_own ON orders;
CREATE POLICY orders_insert_own ON orders FOR INSERT
    WITH CHECK (user_id = nullif(current_setting('app.user_id', true), ''));

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
-- ---- end of the shared block ----------------------------------------------

-- Last on purpose: the Orders role can read the order tables only once RLS is on.
-- Same grant as 05-orders-role.sh (INSERT was already there).
GRANT SELECT ON public.orders, public.order_items TO :"role";

COMMIT;
