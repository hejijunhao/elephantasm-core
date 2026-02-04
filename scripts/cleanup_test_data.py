"""
Cleanup script for test data created after a cutoff timestamp.

Usage:
    cd backend
    source venv/bin/activate
    python scripts/cleanup_test_data.py --dry-run  # Preview
    python scripts/cleanup_test_data.py            # Delete

Uses MIGRATION_DATABASE_URL (postgres superuser) to bypass RLS.
"""

import argparse
from datetime import datetime
from sqlmodel import Session, create_engine
from sqlalchemy import text
from sqlalchemy.pool import NullPool

import sys
sys.path.insert(0, '.')

from app.core.config import settings

# Cutoff: delete everything created AFTER this time
CUTOFF = "2026-01-24 15:00:00"

# Tables to clean in FK-safe order (children first, parents last)
TABLES_IN_ORDER = [
    # Dreamer tables
    ("dream_actions", "created_at"),
    ("dream_sessions", "created_at"),
    # Memory packs & IO
    ("memory_packs", "created_at"),
    ("io_configs", "created_at"),
    # Synthesis configs
    ("synthesis_configs", "created_at"),
    # Identity
    ("identity_audit_log", "created_at"),
    ("identities", "created_at"),
    # Junction table
    ("memories_events", "created_at"),
    # Knowledge (audit log first!)
    ("knowledge_audit_log", "created_at"),
    ("knowledge", "created_at"),
    # Core entities
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


def count_records(session: Session, table: str, ts_column: str, cutoff: str) -> int:
    """Count records created after cutoff."""
    try:
        result = session.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE {ts_column} > :cutoff"),
            {"cutoff": cutoff}
        )
        return result.scalar()
    except Exception as e:
        # Table might not exist
        return 0


def delete_records(session: Session, table: str, ts_column: str, cutoff: str) -> int:
    """Delete records created after cutoff. Returns count deleted."""
    try:
        result = session.execute(
            text(f"DELETE FROM {table} WHERE {ts_column} > :cutoff"),
            {"cutoff": cutoff}
        )
        return result.rowcount
    except Exception as e:
        print(f"  Error deleting from {table}: {e}")
        return 0


def main():
    parser = argparse.ArgumentParser(description="Cleanup test data after cutoff timestamp")
    parser.add_argument("--dry-run", action="store_true", help="Preview without deleting")
    parser.add_argument("--cutoff", default=CUTOFF, help=f"Cutoff timestamp (default: {CUTOFF})")
    args = parser.parse_args()

    cutoff = args.cutoff
    print(f"\nCutoff: {cutoff}")
    print(f"Will delete all records created AFTER this time.\n")

    session = get_admin_session()

    try:
        # Count phase
        print(f"{'Table':<25} {'Records to delete':<20}")
        print("-" * 45)

        total = 0
        counts = []
        for table, ts_col in TABLES_IN_ORDER:
            count = count_records(session, table, ts_col, cutoff)
            counts.append((table, ts_col, count))
            if count > 0:
                print(f"{table:<25} {count:<20}")
                total += count

        print("-" * 45)
        print(f"{'TOTAL':<25} {total:<20}")

        if total == 0:
            print("\nNo records to delete.")
            return

        if args.dry_run:
            print("\n[DRY RUN] No changes made.")
            print("Run without --dry-run to delete.")
            return

        # Confirm
        confirm = input(f"\nDelete {total} records? Type 'yes' to confirm: ")
        if confirm.lower() != "yes":
            print("Aborted.")
            return

        # Delete phase
        print("\nDeleting...")
        for table, ts_col, count in counts:
            if count > 0:
                deleted = delete_records(session, table, ts_col, cutoff)
                print(f"  {table}: {deleted} deleted")

        session.commit()
        print("\nDone. All test data removed.")

    except Exception as e:
        session.rollback()
        print(f"Error: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
