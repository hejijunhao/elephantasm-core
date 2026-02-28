"""
Unit tests for RLS context utilities.

Tests the RLS context management functions used by workflow nodes:
- get_user_id_for_anima: User lookup from anima
- session_with_rls_context: Session with RLS context set
"""
import pytest
from uuid import uuid4, UUID
from sqlalchemy import text
from sqlmodel import Session

from app.workflows.utils.rls_context import get_user_id_for_anima, session_with_rls_context
from app.models.database.animas import Anima, AnimaCreate
from app.models.database.user import User, UserCreate
from app.domain.anima_operations import AnimaOperations


class TestGetUserIdForAnima:
    """Tests for get_user_id_for_anima() function."""

    def test_returns_user_id_for_valid_anima(self, rls_session: Session, test_user_context):
        """Test that function returns user_id for valid anima."""
        # Use pre-existing test user (already in DB via test_user_context)
        user_id = test_user_context["user_id"]
        org_id = test_user_context["org_id"]

        # Create anima owned by test user
        anima_data = AnimaCreate(name="Test Anima")
        anima = AnimaOperations.create(rls_session, anima_data, user_id=user_id, organization_id=org_id)
        rls_session.commit()

        # Test
        result = get_user_id_for_anima(anima.id)

        # Verify
        assert result == user_id
        assert isinstance(result, UUID)

    def test_raises_error_for_nonexistent_anima(self):
        """Test that function raises ValueError for non-existent anima."""
        fake_anima_id = uuid4()

        with pytest.raises(ValueError, match=f"Anima {fake_anima_id} not found"):
            get_user_id_for_anima(fake_anima_id)

    def test_raises_error_for_orphaned_anima(self, rls_session: Session, test_user_context):
        """Test that function raises ValueError for anima without user_id.

        Under RLS, an anima with user_id=None is invisible to non-superuser
        sessions, so get_user_id_for_anima raises 'not found' rather than
        'has no user'. This is correct behavior — RLS prevents access.
        """
        orphaned_anima = Anima(
            name="Orphaned Anima",
            user_id=None,
            organization_id=test_user_context["org_id"],
        )
        rls_session.add(orphaned_anima)
        rls_session.commit()

        with pytest.raises(ValueError, match="not found"):
            get_user_id_for_anima(orphaned_anima.id)


class TestSessionWithRLSContext:
    """Tests for session_with_rls_context() context manager."""

    def test_sets_rls_context_variable(self, test_user_context):
        """Test that session variable is set correctly."""
        user_id = test_user_context["user_id"]

        with session_with_rls_context(user_id) as session:
            result = session.execute(
                text("SELECT current_setting('app.current_user', true)")
            ).scalar()
            assert result == str(user_id)

    def test_commits_on_success(self, test_user_context):
        """Test that changes are committed on successful exit."""
        user_id = test_user_context["user_id"]
        org_id = test_user_context["org_id"]

        anima_id = None
        with session_with_rls_context(user_id) as session:
            anima_data = AnimaCreate(name="Test RLS Commit Anima")
            anima = AnimaOperations.create(session, anima_data, user_id=user_id, organization_id=org_id)
            session.flush()
            anima_id = anima.id

        # Verify anima was persisted
        assert anima_id is not None
        with session_with_rls_context(user_id) as session:
            persisted = session.get(Anima, anima_id)
            assert persisted is not None
            assert persisted.name == "Test RLS Commit Anima"
            # Cleanup via SQL (avoids ORM cascade triggering RLS issues)
            session.execute(text("DELETE FROM synthesis_configs WHERE anima_id = :aid"), {"aid": anima_id})
            session.execute(text("DELETE FROM io_configs WHERE anima_id = :aid"), {"aid": anima_id})
            session.execute(text("DELETE FROM animas WHERE id = :aid"), {"aid": anima_id})

    def test_rolls_back_on_exception(self, test_user_context):
        """Test that changes are rolled back on exception."""
        user_id = test_user_context["user_id"]
        org_id = test_user_context["org_id"]

        anima_id = None
        with pytest.raises(RuntimeError, match="Intentional error"):
            with session_with_rls_context(user_id) as session:
                anima_data = AnimaCreate(name="Test RLS Rollback Anima")
                anima = AnimaOperations.create(session, anima_data, user_id=user_id, organization_id=org_id)
                session.flush()
                anima_id = anima.id
                raise RuntimeError("Intentional error")

        # Verify anima was NOT persisted (rollback worked)
        with session_with_rls_context(user_id) as session:
            if anima_id:
                persisted = session.get(Anima, anima_id)
                assert persisted is None

    def test_session_lifecycle(self, test_user_context):
        """Test that session lifecycle is managed correctly."""
        user_id = test_user_context["user_id"]

        with session_with_rls_context(user_id) as session:
            assert session.is_active
            result = session.execute(text("SELECT 1")).scalar()
            assert result == 1

    def test_isolation_between_contexts(self, test_user_context):
        """Test that RLS context is isolated between different sessions.

        Uses two separate session_with_rls_context calls with the same user
        to verify each session independently sets the context variable.
        """
        user_id = test_user_context["user_id"]

        # First context
        with session_with_rls_context(user_id) as session:
            result = session.execute(
                text("SELECT current_setting('app.current_user', true)")
            ).scalar()
            assert result == str(user_id)

        # Second context (fresh session, should also have correct user)
        with session_with_rls_context(user_id) as session:
            result = session.execute(
                text("SELECT current_setting('app.current_user', true)")
            ).scalar()
            assert result == str(user_id)
