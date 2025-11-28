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

    def test_returns_user_id_for_valid_anima(self, db_session: Session):
        """Test that function returns user_id for valid anima."""
        # Create user
        user = User(
            auth_uid=uuid4(),
            email=f"test_{uuid4()}@example.com"
        )
        db_session.add(user)
        db_session.commit()

        # Create anima owned by user
        anima_data = AnimaCreate(name="Test Anima")
        anima = AnimaOperations.create(db_session, anima_data, user_id=user.id)
        db_session.commit()

        # Test
        result = get_user_id_for_anima(anima.id)

        # Verify
        assert result == user.id
        assert isinstance(result, UUID)

    def test_raises_error_for_nonexistent_anima(self):
        """Test that function raises ValueError for non-existent anima."""
        fake_anima_id = uuid4()

        with pytest.raises(ValueError, match=f"Anima {fake_anima_id} not found"):
            get_user_id_for_anima(fake_anima_id)

    def test_raises_error_for_orphaned_anima(self, db_session: Session):
        """Test that function raises ValueError for anima without user_id."""
        # Create anima without user_id (manually bypass domain layer)
        orphaned_anima = Anima(
            name="Orphaned Anima",
            user_id=None  # Intentionally orphaned
        )
        db_session.add(orphaned_anima)
        db_session.commit()

        with pytest.raises(ValueError, match=f"Anima {orphaned_anima.id} has no user"):
            get_user_id_for_anima(orphaned_anima.id)


class TestSessionWithRLSContext:
    """Tests for session_with_rls_context() context manager."""

    def test_sets_rls_context_variable(self, db_session: Session):
        """Test that session variable is set correctly."""
        # Create user
        user = User(
            auth_uid=uuid4(),
            email=f"test_{uuid4()}@example.com"
        )
        db_session.add(user)
        db_session.commit()

        # Use context manager
        with session_with_rls_context(user.id) as session:
            # Query session variable
            result = session.execute(
                text("SELECT current_setting('app.current_user', true)")
            ).scalar()

            # Verify variable is set
            assert result == str(user.id)

    def test_commits_on_success(self, db_session: Session):
        """Test that changes are committed on successful exit."""
        # Create user
        user = User(
            auth_uid=uuid4(),
            email=f"test_{uuid4()}@example.com"
        )
        db_session.add(user)
        db_session.commit()

        # Create anima within RLS context
        anima_id = None
        with session_with_rls_context(user.id) as session:
            anima_data = AnimaCreate(name="Test Anima")
            anima = AnimaOperations.create(session, anima_data, user_id=user.id)
            session.flush()
            anima_id = anima.id
            # Context exit should commit

        # Verify anima was persisted
        assert anima_id is not None
        with session_with_rls_context(user.id) as session:
            persisted = session.get(Anima, anima_id)
            assert persisted is not None
            assert persisted.name == "Test Anima"

    def test_rolls_back_on_exception(self, db_session: Session):
        """Test that changes are rolled back on exception."""
        # Create user
        user = User(
            auth_uid=uuid4(),
            email=f"test_{uuid4()}@example.com"
        )
        db_session.add(user)
        db_session.commit()

        # Try to create anima, but raise exception
        anima_id = None
        with pytest.raises(RuntimeError, match="Intentional error"):
            with session_with_rls_context(user.id) as session:
                anima_data = AnimaCreate(name="Test Anima")
                anima = AnimaOperations.create(session, anima_data, user_id=user.id)
                session.flush()
                anima_id = anima.id

                # Raise error before commit
                raise RuntimeError("Intentional error")

        # Verify anima was NOT persisted (rollback worked)
        with session_with_rls_context(user.id) as session:
            if anima_id:
                persisted = session.get(Anima, anima_id)
                assert persisted is None  # Should be rolled back

    def test_session_lifecycle(self, db_session: Session):
        """Test that session lifecycle is managed correctly."""
        # Create user
        user = User(
            auth_uid=uuid4(),
            email=f"test_{uuid4()}@example.com"
        )
        db_session.add(user)
        db_session.commit()

        # Use context manager
        with session_with_rls_context(user.id) as session:
            # Session should be active inside context
            assert session.is_active

            # Should be able to execute queries
            result = session.execute(text("SELECT 1")).scalar()
            assert result == 1

    def test_isolation_between_contexts(self, db_session: Session):
        """Test that RLS context is isolated between different sessions."""
        # Create two users
        user1 = User(
            auth_uid=uuid4(),
            email=f"test1_{uuid4()}@example.com"
        )
        user2 = User(
            auth_uid=uuid4(),
            email=f"test2_{uuid4()}@example.com"
        )
        db_session.add(user1)
        db_session.add(user2)
        db_session.commit()

        # Test user1 context
        with session_with_rls_context(user1.id) as session:
            result = session.execute(
                text("SELECT current_setting('app.current_user', true)")
            ).scalar()
            assert result == str(user1.id)

        # Test user2 context (should be different)
        with session_with_rls_context(user2.id) as session:
            result = session.execute(
                text("SELECT current_setting('app.current_user', true)")
            ).scalar()
            assert result == str(user2.id)
