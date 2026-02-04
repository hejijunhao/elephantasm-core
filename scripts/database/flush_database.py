#!/usr/bin/env python3
"""
Database Flush Script

Deletes all user data while preserving:
- User accounts (auth.users, public.users)
- RLS policies
- Database schema and configurations

Tables deleted (in order):
1. identity_audit_log
2. knowledge_audit_log
3. memories_events
4. memory_packs
5. identities
6. knowledge
7. memories
8. events
9. io_configs
10. synthesis_configs
11. animas

Usage:
    python scripts/database/flush_database.py [--confirm]

    Without --confirm: Dry-run mode (shows what would be deleted)
    With --confirm: Actually deletes data
"""

import sys
import argparse
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text
from app.core.config import settings

# Use MIGRATION_DATABASE_URL for direct access (bypasses RLS)
# Similar to migrations - need to see ALL data regardless of user context
# Force psycopg (v3) driver instead of default psycopg2
migration_url = settings.MIGRATION_DATABASE_URL.replace("postgresql://", "postgresql+psycopg://")
engine = create_engine(
    migration_url,
    echo=False,
    pool_pre_ping=True
)


def count_records(table_name: str) -> int:
    """Count records in a table."""
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
        return result.scalar()


def delete_table_data(table_name: str, confirm: bool = False) -> int:
    """Delete all data from a table."""
    count = count_records(table_name)

    if count == 0:
        print(f"  ✓ {table_name}: already empty")
        return 0

    if confirm:
        with engine.connect() as conn:
            conn.execute(text(f"DELETE FROM {table_name}"))
            conn.commit()
            print(f"  ✗ {table_name}: deleted {count} records")
    else:
        print(f"  ○ {table_name}: would delete {count} records")

    return count


def flush_database(confirm: bool = False):
    """
    Flush all user data from database.

    Args:
        confirm: If True, actually delete data. If False, dry-run mode.
    """
    print("=" * 60)
    print("DATABASE FLUSH SCRIPT")
    print("=" * 60)
    print()

    if confirm:
        print("⚠️  LIVE MODE: Data will be PERMANENTLY DELETED")
    else:
        print("📋 DRY-RUN MODE: No data will be deleted (preview only)")

    print()
    print("Tables to preserve:")
    print("  ✓ users (public.users)")
    print("  ✓ auth.users (Supabase)")
    print("  ✓ RLS policies")
    print("  ✓ Database schema")
    print()

    # Deletion order (respects foreign key constraints)
    tables_to_flush = [
        # Layer 1: Audit logs (no dependents)
        "identity_audit_log",   # References identities + memories
        "knowledge_audit_log",  # References knowledge + memories
        # Layer 2: Junction tables and leaf entities
        "memories_events",      # Junction table (CASCADE)
        "memory_packs",         # References animas
        # Layer 3: Core entities with FK to animas
        "identities",           # References animas
        "knowledge",            # References animas
        "memories",             # References animas
        "events",               # References animas
        "io_configs",           # References animas (auto-recreates on access)
        "synthesis_configs",    # References animas (auto-recreates on access)
        # Layer 4: Root entity
        "animas",               # References users
    ]

    print("Tables to flush:")
    total_deleted = 0

    for table in tables_to_flush:
        deleted = delete_table_data(table, confirm)
        total_deleted += deleted

    print()
    print("=" * 60)

    if confirm:
        print(f"✓ COMPLETED: Deleted {total_deleted} total records")
        print()
        print("Next steps:")
        print("  1. synthesis_configs and io_configs will auto-recreate on next access")
        print("  2. Users can create new animas from fresh state")
        print("  3. All RLS policies remain active")
    else:
        print(f"📊 DRY-RUN SUMMARY: Would delete {total_deleted} total records")
        print()
        print("To actually delete data, run:")
        print("  python scripts/database/flush_database.py --confirm")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Flush all user data from database (preserves user accounts)"
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually delete data (without this, runs in dry-run mode)"
    )

    args = parser.parse_args()

    # Safety confirmation in live mode
    if args.confirm:
        print()
        print("⚠️  WARNING: This will PERMANENTLY DELETE all data!")
        print()
        response = input("Type 'DELETE ALL DATA' to confirm: ")

        if response != "DELETE ALL DATA":
            print("❌ Aborted (confirmation text did not match)")
            sys.exit(1)

        print()

    flush_database(confirm=args.confirm)


if __name__ == "__main__":
    main()
