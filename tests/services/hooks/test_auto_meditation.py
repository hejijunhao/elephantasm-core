"""Tests for auto Meditation hook."""

import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4

from app.services.hooks.auto_meditation import (
    trigger_auto_meditation_check,
)


# ─────────────────────────────────────────────────────────────
# trigger_auto_meditation_check (entry point)
# ─────────────────────────────────────────────────────────────


def test_trigger_skipped_when_background_jobs_disabled():
    """Should no-op when ENABLE_BACKGROUND_JOBS=false."""
    with patch("app.core.config.settings") as mock_settings:
        mock_settings.ENABLE_BACKGROUND_JOBS = False

        # Should not raise
        trigger_auto_meditation_check(uuid4(), knowledge_count=1)


def test_trigger_calls_check_and_trigger():
    """Should call _check_and_trigger when background jobs enabled."""
    anima_id = uuid4()

    with patch("app.core.config.settings") as mock_settings, \
         patch("app.services.hooks.auto_meditation._check_and_trigger") as mock_check:
        mock_settings.ENABLE_BACKGROUND_JOBS = True

        trigger_auto_meditation_check(anima_id, knowledge_count=3)

        mock_check.assert_called_once_with(anima_id, 3)


def test_trigger_swallows_exceptions():
    """Should catch and log errors without raising (fire-and-forget)."""
    with patch("app.core.config.settings") as mock_settings, \
         patch("app.services.hooks.auto_meditation._check_and_trigger",
               side_effect=Exception("DB connection failed")):
        mock_settings.ENABLE_BACKGROUND_JOBS = True

        # Should not raise
        trigger_auto_meditation_check(uuid4())


# ─────────────────────────────────────────────────────────────
# _check_and_trigger (counter logic — tested via public entry point)
# ─────────────────────────────────────────────────────────────


def _make_mock_session_ctx(mock_db):
    """Helper: create a mock context manager that yields mock_db."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def test_counter_increment_below_threshold():
    """Should increment counter and skip when below threshold."""
    anima_id = uuid4()
    mock_db = MagicMock()
    mock_ops = MagicMock()
    mock_ops.increment_synth_count.return_value = (3, 10)

    with patch("app.core.config.settings") as mock_settings, \
         patch("app.core.database.get_cron_db_session",
               return_value=_make_mock_session_ctx(mock_db)), \
         patch("app.domain.meditator_operations.MeditatorOperations", mock_ops):
        mock_settings.ENABLE_BACKGROUND_JOBS = True

        trigger_auto_meditation_check(anima_id, knowledge_count=1)

        mock_ops.increment_synth_count.assert_called_once_with(mock_db, anima_id, count=1)
        mock_db.commit.assert_called_once()
        # Should NOT check running session (threshold not reached)
        mock_ops.has_running_session.assert_not_called()


def test_counter_increments_by_knowledge_count():
    """Should pass knowledge_count to single atomic increment call."""
    anima_id = uuid4()
    mock_db = MagicMock()
    mock_ops = MagicMock()
    mock_ops.increment_synth_count.return_value = (5, 10)

    with patch("app.core.config.settings") as mock_settings, \
         patch("app.core.database.get_cron_db_session",
               return_value=_make_mock_session_ctx(mock_db)), \
         patch("app.domain.meditator_operations.MeditatorOperations", mock_ops):
        mock_settings.ENABLE_BACKGROUND_JOBS = True

        trigger_auto_meditation_check(anima_id, knowledge_count=3)

        mock_ops.increment_synth_count.assert_called_once_with(mock_db, anima_id, count=3)


def test_skips_when_session_already_running():
    """Should skip when meditation is already running for this Anima."""
    anima_id = uuid4()
    mock_db = MagicMock()
    mock_ops = MagicMock()
    mock_ops.increment_synth_count.return_value = (10, 10)
    mock_ops.has_running_session.return_value = True

    with patch("app.core.config.settings") as mock_settings, \
         patch("app.core.database.get_cron_db_session",
               return_value=_make_mock_session_ctx(mock_db)), \
         patch("app.domain.meditator_operations.MeditatorOperations", mock_ops):
        mock_settings.ENABLE_BACKGROUND_JOBS = True

        trigger_auto_meditation_check(anima_id, knowledge_count=1)

        mock_ops.has_running_session.assert_called_once_with(mock_db, anima_id)


def test_triggers_when_threshold_reached():
    """Should acquire advisory lock and fire when threshold reached."""
    anima_id = uuid4()
    mock_db = MagicMock()
    mock_ops = MagicMock()
    mock_ops.increment_synth_count.return_value = (10, 10)
    mock_ops.has_running_session.return_value = False

    mock_lock_ctx = MagicMock()
    mock_lock_ctx.__enter__ = MagicMock(return_value=True)
    mock_lock_ctx.__exit__ = MagicMock(return_value=False)

    with patch("app.core.config.settings") as mock_settings, \
         patch("app.core.database.get_cron_db_session",
               return_value=_make_mock_session_ctx(mock_db)), \
         patch("app.domain.meditator_operations.MeditatorOperations", mock_ops), \
         patch("app.services.scheduler.advisory_lock.advisory_lock",
               return_value=mock_lock_ctx), \
         patch("app.services.hooks.auto_meditation._create_and_fire") as mock_fire:
        mock_settings.ENABLE_BACKGROUND_JOBS = True

        trigger_auto_meditation_check(anima_id, knowledge_count=1)

        mock_fire.assert_called_once_with(anima_id)


def test_skips_when_advisory_lock_not_acquired():
    """Should skip when another machine holds the advisory lock."""
    anima_id = uuid4()
    mock_db = MagicMock()
    mock_ops = MagicMock()
    mock_ops.increment_synth_count.return_value = (10, 10)
    mock_ops.has_running_session.return_value = False

    mock_lock_ctx = MagicMock()
    mock_lock_ctx.__enter__ = MagicMock(return_value=False)
    mock_lock_ctx.__exit__ = MagicMock(return_value=False)

    with patch("app.core.config.settings") as mock_settings, \
         patch("app.core.database.get_cron_db_session",
               return_value=_make_mock_session_ctx(mock_db)), \
         patch("app.domain.meditator_operations.MeditatorOperations", mock_ops), \
         patch("app.services.scheduler.advisory_lock.advisory_lock",
               return_value=mock_lock_ctx), \
         patch("app.services.hooks.auto_meditation._create_and_fire") as mock_fire:
        mock_settings.ENABLE_BACKGROUND_JOBS = True

        trigger_auto_meditation_check(anima_id, knowledge_count=1)

        mock_fire.assert_not_called()


# ─────────────────────────────────────────────────────────────
# _create_and_fire (session creation + background thread)
# ─────────────────────────────────────────────────────────────


def test_create_and_fire_skips_when_no_user_id():
    """Should abort when user_id cannot be resolved for anima."""
    from app.services.hooks.auto_meditation import _create_and_fire

    anima_id = uuid4()

    with patch("app.workflows.utils.rls_context.get_user_id_for_anima", return_value=None):
        # Should not raise
        _create_and_fire(anima_id)


def test_create_and_fire_double_checks_running_session():
    """Should re-check running session inside lock (double-check pattern)."""
    from app.services.hooks.auto_meditation import _create_and_fire

    anima_id = uuid4()
    user_id = uuid4()
    mock_db = MagicMock()
    mock_ops = MagicMock()
    mock_ops.has_running_session.return_value = True

    with patch("app.workflows.utils.rls_context.get_user_id_for_anima", return_value=user_id), \
         patch("app.core.database.get_cron_db_session",
               return_value=_make_mock_session_ctx(mock_db)), \
         patch("app.domain.meditator_operations.MeditatorOperations", mock_ops):

        _create_and_fire(anima_id)

        mock_ops.has_running_session.assert_called_once_with(mock_db, anima_id)
        mock_ops.create_session.assert_not_called()


def test_create_and_fire_creates_session_and_starts_thread():
    """Should create session and spawn background thread."""
    from app.services.hooks.auto_meditation import _create_and_fire

    anima_id = uuid4()
    user_id = uuid4()
    session_id = uuid4()
    mock_db = MagicMock()
    mock_ops = MagicMock()
    mock_ops.has_running_session.return_value = False
    mock_session = MagicMock()
    mock_session.id = session_id
    mock_ops.create_session.return_value = mock_session

    mock_thread_cls = MagicMock()

    with patch("app.workflows.utils.rls_context.get_user_id_for_anima", return_value=user_id), \
         patch("app.core.database.get_cron_db_session",
               return_value=_make_mock_session_ctx(mock_db)), \
         patch("app.domain.meditator_operations.MeditatorOperations", mock_ops), \
         patch("app.services.meditator.meditator_service.run_meditation_background"), \
         patch("threading.Thread", mock_thread_cls):

        _create_and_fire(anima_id)

        mock_ops.create_session.assert_called_once()
        mock_db.commit.assert_called_once()
        mock_thread_cls.assert_called_once()
        mock_thread_cls.return_value.start.assert_called_once()
