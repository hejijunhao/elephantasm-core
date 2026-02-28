"""
Cleanup script for test data.

Two modes:
  --user-email  Delete all entity data for a specific user (by email)
  --cutoff      Delete all records created after a timestamp (legacy mode)

Usage:
    cd backend
    source venv/bin/activate

    # User-targeted cleanup (recommended for test user flush)
    python scripts/cleanup_test_data.py --user-email "test-integration-a@elephantasm.test" --dry-run
    python scripts/cleanup_test_data.py --user-email "test-integration-a@elephantasm.test"

    # Timestamp-based cleanup (legacy)
    python scripts/cleanup_test_data.py --cutoff "2026-01-24 15:00:00" --dry-run
    python scripts/cleanup_test_data.py --cutoff "2026-01-24 15:00:00"

Uses MIGRATION_DATABASE_URL (postgres superuser) to bypass RLS.
"""

import argparse
import sys

from sqlmodel import Session, create_engine
from sqlalchemy import text
from sqlalchemy.pool import NullPool

sys.path.insert(0, '.')

from app.core.config import settings


# ---------------------------------------------------------------------------
# FK-safe table ordering (children first, parents last)
# ---------------------------------------------------------------------------

# Tables with direct anima_id FK — deleted via subquery through animas
TABLES_WITH_ANIMA_FK = [
    "dream_sessions",
    "memory_packs",
    "io_configs",
    "synthesis_configs",
    "identities",
    "knowledge",
    "memories",
    "events",
]

# Tables for timestamp-based cleanup (legacy mode)
TABLES_WITH_TIMESTAMP = [
    ("dream_actions", "created_at"),
    ("dream_sessions", "created_at"),
    ("memory_packs", "created_at"),
    ("io_configs", "created_at"),
    ("synthesis_configs", "created_at"),
    ("identity_audit_log", "created_at"),
    ("identities", "created_at"),
    ("memories_events", "created_at"),
    ("knowledge_audit_log", "created_at"),
    ("knowledge", "created_at"),
    ("memories", "created_at"),
    ("events", "created_at"),
    ("animas", "created_at"),
]


def get_admin_session() -> Session:
    """Get superuser session bypassing RLS."""
    migration_url = settings.MIGRATION_DATABASE_URL
    if migration_url.startswith("postgresql://"):
        migration_url = migration_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(migration_url, poolclass=NullPool)
    return Session(engine)


# ---------------------------------------------------------------------------
# User-targeted cleanup
# ---------------------------------------------------------------------------

def resolve_user_email(session: Session, email: str) -> dict | None:
    """Resolve email to user_id. Returns {"user_id", "email"} or None."""
    result = session.execute(
        text("SELECT id, email FROM users WHERE email = :email AND is_deleted = false"),
        {"email": email}
    )
    row = result.fetchone()
    if row:
        return {"user_id": str(row.id), "email": row.email}
    return None


# Subquery fragment: all anima IDs for a user
_ANIMA_IDS = "SELECT id FROM animas WHERE user_id = :uid"

# Multi-hop queries for tables without direct anima_id FK.
# Order matters — delete children before parents.
MULTI_HOP_QUERIES = [
    # dream_actions → dream_sessions.anima_id
    ("dream_actions", f"""
        DELETE FROM dream_actions
        WHERE session_id IN (
            SELECT id FROM dream_sessions
            WHERE anima_id IN ({_ANIMA_IDS})
        )
    """),
    # identity_audit_log → identities.anima_id
    ("identity_audit_log", f"""
        DELETE FROM identity_audit_log
        WHERE identity_id IN (
            SELECT id FROM identities
            WHERE anima_id IN ({_ANIMA_IDS})
        )
    """),
    # knowledge_audit_log → knowledge.anima_id
    ("knowledge_audit_log", f"""
        DELETE FROM knowledge_audit_log
        WHERE knowledge_id IN (
            SELECT id FROM knowledge
            WHERE anima_id IN ({_ANIMA_IDS})
        )
    """),
    # memories_events → memories.anima_id
    ("memories_events", f"""
        DELETE FROM memories_events
        WHERE memory_id IN (
            SELECT id FROM memories
            WHERE anima_id IN ({_ANIMA_IDS})
        )
    """),
]

# Corresponding COUNT queries (same structure, SELECT COUNT(*) instead of DELETE)
MULTI_HOP_COUNT_QUERIES = [
    (name, q.replace("DELETE FROM " + name, f"SELECT COUNT(*) FROM {name}", 1))
    for name, q in MULTI_HOP_QUERIES
]


def count_user_records(session: Session, user_id: str) -> list[tuple[str, int]]:
    """Count all entity records owned by user. Returns [(table, count), ...]."""
    counts = []

    # Multi-hop tables (audit logs, junction tables, dream_actions)
    for table, query in MULTI_HOP_COUNT_QUERIES:
        r = session.execute(text(query), {"uid": user_id})
        counts.append((table, r.scalar()))

    # Tables with direct anima_id FK
    for table in TABLES_WITH_ANIMA_FK:
        r = session.execute(text(
            f"SELECT COUNT(*) FROM {table} "
            f"WHERE anima_id IN ({_ANIMA_IDS})"
        ), {"uid": user_id})
        counts.append((table, r.scalar()))

    # api_keys (user_id FK, not anima_id)
    r = session.execute(text(
        "SELECT COUNT(*) FROM api_keys WHERE user_id = :uid"
    ), {"uid": user_id})
    counts.append(("api_keys", r.scalar()))

    # animas (root entity)
    r = session.execute(text(
        f"SELECT COUNT(*) FROM animas WHERE user_id = :uid"
    ), {"uid": user_id})
    counts.append(("animas", r.scalar()))

    return counts


def delete_user_records(session: Session, user_id: str) -> list[tuple[str, int]]:
    """Delete all entity records owned by user. Returns [(table, deleted), ...]."""
    deleted = []

    # Multi-hop tables first (children before parents)
    for table, query in MULTI_HOP_QUERIES:
        r = session.execute(text(query), {"uid": user_id})
        deleted.append((table, r.rowcount))

    # Tables with direct anima_id FK
    for table in TABLES_WITH_ANIMA_FK:
        r = session.execute(text(
            f"DELETE FROM {table} "
            f"WHERE anima_id IN ({_ANIMA_IDS})"
        ), {"uid": user_id})
        deleted.append((table, r.rowcount))

    # api_keys
    r = session.execute(text(
        "DELETE FROM api_keys WHERE user_id = :uid"
    ), {"uid": user_id})
    deleted.append(("api_keys", r.rowcount))

    # animas
    r = session.execute(text(
        "DELETE FROM animas WHERE user_id = :uid"
    ), {"uid": user_id})
    deleted.append(("animas", r.rowcount))

    return deleted


def run_user_cleanup(email: str, dry_run: bool):
    """Delete all entity data for a user identified by email."""
    session = get_admin_session()

    try:
        # Resolve email
        user = resolve_user_email(session, email)
        if not user:
            print(f"\nUser not found: {email}")
            return

        user_id = user["user_id"]
        print(f"\nUser: {user['email']} ({user_id})")
        print(f"Mode: {'DRY RUN' if dry_run else 'LIVE DELETE'}\n")

        # Count phase
        counts = count_user_records(session, user_id)

        print(f"{'Table':<25} {'Records':<10}")
        print("-" * 35)

        total = 0
        for table, count in counts:
            if count > 0:
                print(f"{table:<25} {count:<10}")
                total += count

        print("-" * 35)
        print(f"{'TOTAL':<25} {total:<10}")

        if total == 0:
            print("\nNo records to delete.")
            return

        if dry_run:
            print("\n[DRY RUN] No changes made.")
            print("Run without --dry-run to delete.")
            return

        # Confirm
        confirm = input(f"\nDelete {total} records for {email}? Type 'yes' to confirm: ")
        if confirm.lower() != "yes":
            print("Aborted.")
            return

        # Delete phase
        print("\nDeleting...")
        results = delete_user_records(session, user_id)
        for table, count in results:
            if count > 0:
                print(f"  {table}: {count} deleted")

        session.commit()
        print(f"\nDone. All entity data removed for {email}.")
        print("Note: User account preserved (users table untouched).")

    except Exception as e:
        session.rollback()
        print(f"Error: {e}")
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Timestamp-based cleanup (legacy)
# ---------------------------------------------------------------------------

def count_by_timestamp(session: Session, table: str, ts_col: str, cutoff: str) -> int:
    """Count records created after cutoff."""
    try:
        r = session.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE {ts_col} > :cutoff"),
            {"cutoff": cutoff}
        )
        return r.scalar()
    except Exception:
        return 0


def delete_by_timestamp(session: Session, table: str, ts_col: str, cutoff: str) -> int:
    """Delete records created after cutoff. Returns count deleted."""
    try:
        r = session.execute(
            text(f"DELETE FROM {table} WHERE {ts_col} > :cutoff"),
            {"cutoff": cutoff}
        )
        return r.rowcount
    except Exception as e:
        print(f"  Error deleting from {table}: {e}")
        return 0


def run_timestamp_cleanup(cutoff: str, dry_run: bool):
    """Delete all records created after cutoff timestamp."""
    print(f"\nCutoff: {cutoff}")
    print(f"Will delete all records created AFTER this time.\n")

    session = get_admin_session()

    try:
        print(f"{'Table':<25} {'Records to delete':<20}")
        print("-" * 45)

        total = 0
        counts = []
        for table, ts_col in TABLES_WITH_TIMESTAMP:
            count = count_by_timestamp(session, table, ts_col, cutoff)
            counts.append((table, ts_col, count))
            if count > 0:
                print(f"{table:<25} {count:<20}")
                total += count

        print("-" * 45)
        print(f"{'TOTAL':<25} {total:<20}")

        if total == 0:
            print("\nNo records to delete.")
            return

        if dry_run:
            print("\n[DRY RUN] No changes made.")
            print("Run without --dry-run to delete.")
            return

        confirm = input(f"\nDelete {total} records? Type 'yes' to confirm: ")
        if confirm.lower() != "yes":
            print("Aborted.")
            return

        print("\nDeleting...")
        for table, ts_col, count in counts:
            if count > 0:
                deleted = delete_by_timestamp(session, table, ts_col, cutoff)
                print(f"  {table}: {deleted} deleted")

        session.commit()
        print("\nDone. All test data removed.")

    except Exception as e:
        session.rollback()
        print(f"Error: {e}")
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Cleanup test data by user email or cutoff timestamp"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without deleting")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--user-email",
        help="Delete all entity data for user with this email"
    )
    group.add_argument(
        "--cutoff",
        help="Delete all records created after this timestamp (e.g. '2026-01-24 15:00:00')"
    )

    args = parser.parse_args()

    if args.user_email:
        run_user_cleanup(args.user_email, args.dry_run)
    else:
        run_timestamp_cleanup(args.cutoff, args.dry_run)


if __name__ == "__main__":
    main()
