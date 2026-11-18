"""Row-level security, quota and locking against a REAL PostgreSQL.

Run only against the disposable db-test service (see docker-compose.yml,
profile "test"), from a container on the Compose network:

    pytest -m integration tests/integration/test_rls.py

Needs these variables (the runner passes them; none is written here):
INTEGRATION_DB_HOST (db-test; a separate name on purpose, so a mistake can never
point these tests at the development database), DB_PORT, DB_NAME, DB_USER and
DB_PASSWORD (admin), ORDERS_DB_USER and ORDERS_DB_PASSWORD (the service role).
Every test starts from empty order tables. The admin connection is used only to
prepare and check data; everything under test goes through the service role.
"""
from __future__ import annotations

import os
import threading
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.errors import (
    CheckViolation,
    InsufficientPrivilege,
    QueryCanceled,
)

from app.config import Settings
from app.db import OrderLimitExceeded, PostgresOrderRepository

pytestmark = pytest.mark.integration

A = "1be5a62d-ccb5-438b-b8a4-62ecbd8f2912"
B = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
MIGRATION = Path(__file__).resolve().parents[2] / "db" / "migrate-rls.sql"


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not set (run through the db-test runner)")
    return value


def _kwargs(user_var: str, password_var: str) -> dict:
    return {
        "host": _env("INTEGRATION_DB_HOST"),
        "port": int(_env("DB_PORT")),
        "dbname": _env("DB_NAME"),
        "user": _env(user_var),
        "password": _env(password_var),
        "connect_timeout": 5,
        "sslmode": os.environ.get("DB_SSLMODE") or "prefer",
    }


@pytest.fixture
def admin():
    """Owner of the tables (bypasses RLS). Empties the order tables first."""
    with psycopg.connect(**_kwargs("DB_USER", "DB_PASSWORD"), autocommit=True) as conn:
        conn.execute("TRUNCATE order_items, orders")
        yield conn


@pytest.fixture
def orders_role():
    return _kwargs("ORDERS_DB_USER", "ORDERS_DB_PASSWORD")


@contextmanager
def session(kwargs, sub=None):
    """One transaction as the service role, with app.user_id set like db.py does."""
    with psycopg.connect(**kwargs) as conn:    # commits on exit, rolls back on error
        with conn.cursor() as cur:
            if sub is not None:
                cur.execute("SELECT set_config('app.user_id', %s, true)", (sub,))
            yield cur


def make_repo(max_per_hour=10):
    admin_like = _kwargs("ORDERS_DB_USER", "ORDERS_DB_PASSWORD")
    settings = Settings(
        db_host=admin_like["host"],
        db_port=admin_like["port"],
        db_user=admin_like["user"],
        db_password=admin_like["password"],
        db_name=admin_like["dbname"],
        db_sslmode=admin_like["sslmode"],
        cors_allowed_origin="https://shop.example.test",
        cognito_issuer="https://idp.example.test/pool-one",
        cognito_jwks_url="https://idp.example.test/pool-one/jwks.json",
        cognito_app_client_id="testclient0123456789abcdef01",
        max_orders_per_hour=max_per_hour,
    )
    repo = PostgresOrderRepository(settings)
    repo.open()
    return repo


@pytest.fixture
def repo():
    repo = make_repo()
    yield repo
    repo.close()


def admin_order(admin, user_id, hours_ago=0, total="10.00"):
    """Insert an order with one line as the admin. Returns the order id."""
    order_id = uuid.uuid4()
    admin.execute(
        "INSERT INTO orders (id, user_id, total, created_at) "
        "VALUES (%s, %s, %s, now() - make_interval(hours => %s))",
        (order_id, user_id, Decimal(total), hours_ago),
    )
    admin.execute(
        "INSERT INTO order_items (order_id, product_id, name, quantity, unit_price) "
        "VALUES (%s, 1, 'Item', 1, %s)",
        (order_id, Decimal(total)),
    )
    return order_id


def count(admin, table="orders", where="true", params=()):
    return admin.execute(f"SELECT count(*) FROM {table} WHERE {where}", params).fetchone()[0]


# ---------------------------------------------------------------------------
# The role really is subject to RLS
# ---------------------------------------------------------------------------
def test_role_is_not_owner_superuser_or_bypassrls(admin, orders_role):
    role = orders_role["user"]
    row = admin.execute(
        "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = %s", (role,)
    ).fetchone()
    assert row == (False, False)
    for table in ("orders", "order_items"):
        owner, rls = admin.execute(
            "SELECT pg_get_userbyid(relowner), relrowsecurity FROM pg_class "
            "WHERE oid = %s::regclass", (table,)
        ).fetchone()
        assert owner != role
        assert rls is True


def test_role_has_select_and_insert_but_no_update_delete(admin, orders_role):
    role = orders_role["user"]
    for table in ("orders", "order_items"):
        granted = {
            p for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
            if admin.execute("SELECT has_table_privilege(%s, %s, %s)", (role, table, p)).fetchone()[0]
        }
        assert granted == {"SELECT", "INSERT"}


# ---------------------------------------------------------------------------
# Without app.user_id: zero rows
# ---------------------------------------------------------------------------
def test_without_app_user_id_no_row_is_visible(admin, orders_role):
    admin_order(admin, A)
    admin_order(admin, B)
    with session(orders_role) as cur:                      # never set
        assert cur.execute("SELECT count(*) FROM orders").fetchone()[0] == 0
        assert cur.execute("SELECT count(*) FROM order_items").fetchone()[0] == 0


def test_with_an_empty_app_user_id_no_row_is_visible(admin, orders_role):
    admin_order(admin, A)
    with session(orders_role, sub="") as cur:
        assert cur.execute("SELECT count(*) FROM orders").fetchone()[0] == 0
        assert cur.execute("SELECT count(*) FROM order_items").fetchone()[0] == 0


def test_app_user_id_does_not_survive_the_transaction(admin, orders_role):
    admin_order(admin, A)
    with psycopg.connect(**orders_role) as conn:
        conn.execute("SELECT set_config('app.user_id', %s, true)", (A,))
        assert conn.execute("SELECT count(*) FROM orders").fetchone()[0] == 1
        conn.rollback()                                    # transaction 1 ends
        value = conn.execute("SELECT current_setting('app.user_id', true)").fetchone()[0]
        assert value in (None, "")                         # PostgreSQL gives one or the other
        assert conn.execute("SELECT count(*) FROM orders").fetchone()[0] == 0
        conn.execute("SELECT set_config('app.user_id', %s, true)", (A,))
        conn.commit()                                      # transaction 2 ends
        value = conn.execute("SELECT current_setting('app.user_id', true)").fetchone()[0]
        assert value in (None, "")
        assert conn.execute("SELECT count(*) FROM orders").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# A sees only A
# ---------------------------------------------------------------------------
def test_each_customer_sees_only_their_own_orders_and_lines(admin, orders_role):
    a1, a2, b1 = admin_order(admin, A), admin_order(admin, A), admin_order(admin, B)
    with session(orders_role, sub=A) as cur:
        assert {r[0] for r in cur.execute("SELECT id FROM orders")} == {a1, a2}
        assert cur.execute("SELECT count(*) FROM order_items").fetchone()[0] == 2
        # Knowing another customer's order id does not help.
        assert cur.execute("SELECT count(*) FROM orders WHERE id = %s", (b1,)).fetchone()[0] == 0
        assert cur.execute("SELECT count(*) FROM order_items WHERE order_id = %s", (b1,)).fetchone()[0] == 0
    with session(orders_role, sub=B) as cur:
        assert {r[0] for r in cur.execute("SELECT id FROM orders")} == {b1}


def test_legacy_anonymous_orders_are_invisible_to_everyone(admin, orders_role):
    # Orders made before Cognito have user_id NULL. The NOT VALID constraint
    # refuses new ones, so recreate the old state by hand for this test.
    legacy = uuid.uuid4()
    admin.execute("ALTER TABLE orders DROP CONSTRAINT orders_user_required")
    try:
        admin.execute("INSERT INTO orders (id, user_id, total) VALUES (%s, NULL, 5)", (legacy,))
        admin.execute(
            "INSERT INTO order_items (order_id, product_id, name, quantity, unit_price) "
            "VALUES (%s, 1, 'Item', 1, 5)", (legacy,))
    finally:
        admin.execute(
            "ALTER TABLE orders ADD CONSTRAINT orders_user_required "
            "CHECK (user_id IS NOT NULL) NOT VALID"
        )
    for sub in (None, "", A, B):
        with session(orders_role, sub=sub) as cur:
            assert cur.execute("SELECT count(*) FROM orders").fetchone()[0] == 0
            assert cur.execute("SELECT count(*) FROM order_items").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# A cannot insert as B
# ---------------------------------------------------------------------------
def insert_order(cur, user_id, order_id=None):
    order_id = order_id or uuid.uuid4()
    cur.execute(
        "INSERT INTO orders (id, user_id, total) VALUES (%s, %s, 10)", (order_id, user_id)
    )
    return order_id


def test_a_cannot_insert_an_order_for_b(admin, orders_role):
    with pytest.raises(InsufficientPrivilege):
        with session(orders_role, sub=A) as cur:
            insert_order(cur, B)
    assert count(admin) == 0


def test_insert_without_app_user_id_is_refused(admin, orders_role):
    with pytest.raises(InsufficientPrivilege):
        with session(orders_role) as cur:
            insert_order(cur, A)
    assert count(admin) == 0


def test_insert_with_null_user_id_is_refused(admin, orders_role):
    with pytest.raises(InsufficientPrivilege):
        with session(orders_role, sub=A) as cur:
            insert_order(cur, None)
    assert count(admin) == 0


def test_a_cannot_add_lines_to_bs_order(admin, orders_role):
    b_order = admin_order(admin, B)
    with pytest.raises(InsufficientPrivilege):
        with session(orders_role, sub=A) as cur:
            cur.execute(
                "INSERT INTO order_items (order_id, product_id, name, quantity, unit_price) "
                "VALUES (%s, 2, 'Injected', 1, 1)", (b_order,))
    assert count(admin, "order_items", "order_id = %s", (b_order,)) == 1


def test_a_can_insert_their_own_order_and_lines(admin, orders_role):
    with session(orders_role, sub=A) as cur:
        order_id = insert_order(cur, A)
        cur.execute(
            "INSERT INTO order_items (order_id, product_id, name, quantity, unit_price) "
            "VALUES (%s, 1, 'Item', 1, 10)", (order_id,))
    assert count(admin, "orders", "user_id = %s", (A,)) == 1
    assert count(admin, "order_items") == 1


def test_insert_returning_passes_the_select_policy(orders_role):
    # The service does not use RETURNING (it generates the id itself), but it
    # must keep working if it ever does: the new row passes the SELECT policy.
    with session(orders_role, sub=A) as cur:
        order_id = uuid.uuid4()
        row = cur.execute(
            "INSERT INTO orders (id, user_id, total) VALUES (%s, %s, 10) RETURNING id, user_id",
            (order_id, A),
        ).fetchone()
        assert row == (order_id, A)
        line = cur.execute(
            "INSERT INTO order_items (order_id, product_id, name, quantity, unit_price) "
            "VALUES (%s, 1, 'Item', 1, 10) RETURNING order_id", (order_id,)
        ).fetchone()
        assert line == (order_id,)


def test_insert_returning_cannot_be_used_to_read_or_write_for_b(admin, orders_role):
    with pytest.raises(InsufficientPrivilege):
        with session(orders_role, sub=A) as cur:
            cur.execute(
                "INSERT INTO orders (id, user_id, total) VALUES (%s, %s, 10) RETURNING id",
                (uuid.uuid4(), B),
            )
    assert count(admin) == 0


def test_update_delete_and_truncate_are_denied(admin, orders_role):
    admin_order(admin, A)
    for statement in (
        "UPDATE orders SET total = 0",
        "DELETE FROM orders",
        "UPDATE order_items SET quantity = 99",
        "DELETE FROM order_items",
        "TRUNCATE orders CASCADE",
    ):
        with pytest.raises(InsufficientPrivilege):
            with session(orders_role, sub=A) as cur:
                cur.execute(statement)
    assert count(admin) == 1 and count(admin, "order_items") == 1


def test_admin_cannot_store_an_order_without_a_customer(admin):
    with pytest.raises(CheckViolation):
        admin.execute("INSERT INTO orders (id, user_id, total) VALUES (%s, NULL, 1)", (uuid.uuid4(),))
    validated = admin.execute(
        "SELECT convalidated FROM pg_constraint WHERE conname = 'orders_user_required'"
    ).fetchone()[0]
    assert validated is False        # NOT VALID: old rows are not checked


# ---------------------------------------------------------------------------
# The repository, end to end
# ---------------------------------------------------------------------------
def test_repository_stores_the_sub_and_isolates_history(admin, repo):
    created = repo.create_order(A, [(1, 2), (3, 1)])
    assert count(admin, "orders", "id = %s AND user_id = %s", (created["id"], A)) == 1
    mine = repo.list_orders(A, 20)
    assert [o["id"] for o in mine] == [created["id"]]
    assert mine[0]["total"] == created["total"]
    assert [(l["product_id"], l["quantity"]) for l in mine[0]["items"]] == [(1, 2), (3, 1)]
    assert repo.list_orders(B, 20) == []


def test_history_is_newest_first_and_respects_the_limit(admin, repo):
    old, new = admin_order(admin, A, hours_ago=5), admin_order(admin, A, hours_ago=1)
    admin_order(admin, B)
    assert [o["id"] for o in repo.list_orders(A, 20)] == [new, old]
    assert [o["id"] for o in repo.list_orders(A, 1)] == [new]


def test_per_customer_limit_counts_only_the_last_hour(admin):
    admin_order(admin, A, hours_ago=3)      # too old to count
    repo = make_repo(max_per_hour=2)
    try:
        repo.create_order(A, [(1, 1)])
        repo.create_order(A, [(1, 1)])
        with pytest.raises(OrderLimitExceeded):
            repo.create_order(A, [(1, 1)])
        repo.create_order(B, [(1, 1)])      # another customer is not affected
    finally:
        repo.close()
    assert count(admin, "orders", "user_id = %s", (A,)) == 3     # 1 old + 2 new
    assert count(admin, "orders", "user_id = %s", (B,)) == 1


def test_a_refused_order_leaves_nothing_behind(admin):
    repo = make_repo(max_per_hour=1)
    try:
        repo.create_order(A, [(1, 1)])
        with pytest.raises(OrderLimitExceeded):
            repo.create_order(A, [(1, 1)])
    finally:
        repo.close()
    assert count(admin) == 1 and count(admin, "order_items") == 1


# ---------------------------------------------------------------------------
# The advisory lock
# ---------------------------------------------------------------------------
def test_role_can_execute_the_advisory_lock_function(admin, orders_role):
    assert admin.execute(
        "SELECT has_function_privilege(%s, 'pg_advisory_xact_lock(bigint)', 'EXECUTE')",
        (orders_role["user"],),
    ).fetchone()[0] is True
    with session(orders_role, sub=A) as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s::text))", (A,))


def test_concurrent_orders_of_one_customer_cannot_skip_the_limit(admin):
    limit, attempts = 3, 8
    repo = make_repo(max_per_hour=limit)
    barrier = threading.Barrier(attempts)
    results = []

    def attempt():
        barrier.wait()
        try:
            repo.create_order(A, [(1, 1)])
            results.append("ok")
        except OrderLimitExceeded:
            results.append("limit")
        except Exception as exc:   # anything else is a failure of the test
            results.append(type(exc).__name__)

    threads = [threading.Thread(target=attempt) for _ in range(attempts)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
    finally:
        repo.close()
    assert sorted(results) == ["limit"] * (attempts - limit) + ["ok"] * limit
    assert count(admin, "orders", "user_id = %s", (A,)) == limit


def test_the_lock_blocks_the_same_customer_but_not_another(admin, orders_role):
    hash_a, hash_b = (
        admin.execute("SELECT hashtext(%s::text)", (sub,)).fetchone()[0] for sub in (A, B)
    )
    assert hash_a != hash_b
    holder = psycopg.connect(**orders_role)
    waiter = psycopg.connect(**orders_role)
    try:
        holder.execute("SELECT pg_advisory_xact_lock(hashtext(%s::text))", (A,))
        waiter.execute("SET statement_timeout = 500")
        waiter.commit()
        with pytest.raises(QueryCanceled):                  # same customer waits
            waiter.execute("SELECT pg_advisory_xact_lock(hashtext(%s::text))", (A,))
        waiter.rollback()
        waiter.execute("SELECT pg_advisory_xact_lock(hashtext(%s::text))", (B,))   # another does not
        waiter.rollback()
        holder.rollback()                                   # lock released with the transaction
        waiter.execute("SELECT pg_advisory_xact_lock(hashtext(%s::text))", (A,))
        waiter.rollback()
    finally:
        holder.close()
        waiter.close()


# ---------------------------------------------------------------------------
# The migration
# ---------------------------------------------------------------------------
def _state(admin, role):
    """Everything the migration is supposed to produce, in a comparable form."""
    policies = admin.execute(
        "SELECT tablename, policyname, cmd, roles::text, qual, with_check "
        "FROM pg_policies WHERE schemaname = 'public' ORDER BY 1, 2"
    ).fetchall()
    rls = admin.execute(
        "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
        "WHERE relname IN ('orders','order_items') ORDER BY 1"
    ).fetchall()
    constraint = admin.execute(
        "SELECT pg_get_constraintdef(oid), convalidated FROM pg_constraint "
        "WHERE conname = 'orders_user_required'"
    ).fetchall()
    grants = admin.execute(
        "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
        "WHERE grantee = %s AND table_name IN ('orders','order_items') ORDER BY 1, 2", (role,)
    ).fetchall()
    return policies, rls, constraint, grants


def test_migration_is_idempotent_and_matches_schema_sql(admin, orders_role):
    role = orders_role["user"]
    before = _state(admin, role)                 # database built from schema.sql
    assert before[0], "schema.sql should have created the policies"
    text = MIGRATION.read_text().replace(':"role"', sql.Identifier(role).as_string(admin))
    assert ":" + '"' not in text
    for _ in range(2):                           # twice: the second run changes nothing
        admin.execute(text)
        assert _state(admin, role) == before
