"""Test JWT authentication utilities with JWKS."""

import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from uuid import uuid4
from fastapi import HTTPException

from app.core.auth import get_current_user_id, require_current_user_id
from app.models.database.user import User


@pytest.fixture
def mock_user():
    """Create a mock user for testing."""
    user = Mock(spec=User)
    user.id = uuid4()
    user.auth_uid = str(uuid4())
    user.email = "test@example.com"
    return user


@pytest.fixture
def mock_public_key():
    """Mock ECC P-256 public key (PEM format)."""
    return """-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEVsMupSb6o7dBIr+fXHp8i
mANTdlkPMtP6U9A3j+9k7pJZFqHhkjJQPnXU3d8JA1BqL4TzN5RwQ7p
-----END PUBLIC KEY-----"""


@pytest.mark.asyncio
async def test_get_current_user_id_no_header():
    """Test that missing Authorization header returns None."""
    result = await get_current_user_id(authorization=None)
    assert result is None


@pytest.mark.asyncio
async def test_get_current_user_id_invalid_format():
    """Test that non-Bearer token returns None."""
    result = await get_current_user_id(authorization="InvalidFormat token123")
    assert result is None


@pytest.mark.asyncio
async def test_get_current_user_id_no_supabase_url():
    """Test that missing Supabase URL returns None (dev mode)."""
    with patch("app.core.auth.settings") as mock_settings:
        mock_settings.SUPABASE_URL = ""

        result = await get_current_user_id(authorization="Bearer valid-token")
        assert result is None


@pytest.mark.asyncio
async def test_get_current_user_id_valid_token(mock_user, mock_public_key):
    """Test successful JWT validation and user lookup with JWKS."""
    with patch("app.core.auth.settings") as mock_settings:
        mock_settings.SUPABASE_URL = "https://test.supabase.co"

        with patch("app.core.auth.jwt.get_unverified_header") as mock_get_header:
            # Mock JWT header to return kid
            mock_get_header.return_value = {"kid": "test-kid-123", "alg": "ES256"}

            with patch("app.core.auth.auth_cache.get_key", new_callable=AsyncMock) as mock_get_key:
                # Mock auth cache to return public key
                mock_get_key.return_value = mock_public_key

                with patch("app.core.auth.jwt.decode") as mock_decode:
                    # Mock JWT decode to return valid payload
                    mock_decode.return_value = {
                        "sub": mock_user.auth_uid,
                        "email": mock_user.email,
                        "exp": 9999999999
                    }

                    with patch("app.core.auth.SessionLocal") as mock_session_class:
                        # Mock database session and query
                        mock_session = MagicMock()
                        mock_session_class.return_value = mock_session

                        # Two-phase bootstrap: (1) SET auth_uid, (2) SELECT user
                        # First call returns set_config result, second returns user query
                        mock_set_result = Mock()
                        mock_user_result = Mock()
                        mock_user_result.scalar_one_or_none.return_value = mock_user
                        mock_session.execute.side_effect = [mock_set_result, mock_user_result]

                        # Execute test
                        result = await get_current_user_id(authorization="Bearer valid-token")

                        # Verify
                        assert result == mock_user.id
                        # Verify JWKS cache was used
                        mock_get_key.assert_called_once_with("test-kid-123")
                        # Verify ES256 algorithm was used
                        mock_decode.assert_called_once()
                        call_args = mock_decode.call_args
                        assert call_args[1]["algorithms"] == ["ES256"]
                        # Two-phase bootstrap: SET auth_uid + SELECT user
                        assert mock_session.execute.call_count == 2
                        mock_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_get_current_user_id_no_kid_in_header(mock_public_key):
    """Test that token without kid in header returns None."""
    with patch("app.core.auth.settings") as mock_settings:
        mock_settings.SUPABASE_URL = "https://test.supabase.co"

        with patch("app.core.auth.jwt.get_unverified_header") as mock_get_header:
            # Mock JWT header without kid
            mock_get_header.return_value = {"alg": "ES256"}  # Missing kid

            result = await get_current_user_id(authorization="Bearer no-kid-token")
            assert result is None


@pytest.mark.asyncio
async def test_get_current_user_id_key_not_found(mock_public_key):
    """Test that token with unknown kid returns None."""
    with patch("app.core.auth.settings") as mock_settings:
        mock_settings.SUPABASE_URL = "https://test.supabase.co"

        with patch("app.core.auth.jwt.get_unverified_header") as mock_get_header:
            mock_get_header.return_value = {"kid": "unknown-kid", "alg": "ES256"}

            with patch("app.core.auth.auth_cache.get_key", new_callable=AsyncMock) as mock_get_key:
                # Mock JWKS cache returning None (key not found)
                mock_get_key.return_value = None

                result = await get_current_user_id(authorization="Bearer unknown-kid-token")
                assert result is None


@pytest.mark.asyncio
async def test_get_current_user_id_expired_token(mock_public_key):
    """Test that expired JWT token returns None (JWKS)."""
    from jose import jwt as jose_jwt

    with patch("app.core.auth.settings") as mock_settings:
        mock_settings.SUPABASE_URL = "https://test.supabase.co"

        with patch("app.core.auth.jwt.get_unverified_header") as mock_get_header:
            mock_get_header.return_value = {"kid": "test-kid-123", "alg": "ES256"}

            with patch("app.core.auth.auth_cache.get_key", new_callable=AsyncMock) as mock_get_key:
                mock_get_key.return_value = mock_public_key

                with patch("app.core.auth.jwt.decode") as mock_decode:
                    # Mock JWT decode to raise ExpiredSignatureError
                    mock_decode.side_effect = jose_jwt.ExpiredSignatureError("Token expired")

                    result = await get_current_user_id(authorization="Bearer expired-token")
                    assert result is None


@pytest.mark.asyncio
async def test_get_current_user_id_invalid_token(mock_public_key):
    """Test that invalid JWT token returns None (JWKS)."""
    from jose import JWTError

    with patch("app.core.auth.settings") as mock_settings:
        mock_settings.SUPABASE_URL = "https://test.supabase.co"

        with patch("app.core.auth.jwt.get_unverified_header") as mock_get_header:
            mock_get_header.return_value = {"kid": "test-kid-123", "alg": "ES256"}

            with patch("app.core.auth.auth_cache.get_key", new_callable=AsyncMock) as mock_get_key:
                mock_get_key.return_value = mock_public_key

                with patch("app.core.auth.jwt.decode") as mock_decode:
                    # Mock JWT decode to raise JWTError
                    mock_decode.side_effect = JWTError("Invalid token")

                    result = await get_current_user_id(authorization="Bearer invalid-token")
                    assert result is None


@pytest.mark.asyncio
async def test_get_current_user_id_no_sub_claim(mock_public_key):
    """Test that token without 'sub' claim returns None (JWKS)."""
    with patch("app.core.auth.settings") as mock_settings:
        mock_settings.SUPABASE_URL = "https://test.supabase.co"

        with patch("app.core.auth.jwt.get_unverified_header") as mock_get_header:
            mock_get_header.return_value = {"kid": "test-kid-123", "alg": "ES256"}

            with patch("app.core.auth.auth_cache.get_key", new_callable=AsyncMock) as mock_get_key:
                mock_get_key.return_value = mock_public_key

                with patch("app.core.auth.jwt.decode") as mock_decode:
                    # Mock JWT decode to return payload without 'sub'
                    mock_decode.return_value = {
                        "email": "test@example.com",
                        "exp": 9999999999
                    }

                    result = await get_current_user_id(authorization="Bearer no-sub-token")
                    assert result is None


@pytest.mark.asyncio
async def test_get_current_user_id_user_not_in_db(mock_user, mock_public_key):
    """Test that valid token but user not in DB returns None (JWKS)."""
    with patch("app.core.auth.settings") as mock_settings:
        mock_settings.SUPABASE_URL = "https://test.supabase.co"

        with patch("app.core.auth.jwt.get_unverified_header") as mock_get_header:
            mock_get_header.return_value = {"kid": "test-kid-123", "alg": "ES256"}

            with patch("app.core.auth.auth_cache.get_key", new_callable=AsyncMock) as mock_get_key:
                mock_get_key.return_value = mock_public_key

                with patch("app.core.auth.jwt.decode") as mock_decode:
                    mock_decode.return_value = {
                        "sub": mock_user.auth_uid,
                        "email": mock_user.email,
                        "exp": 9999999999
                    }

                    with patch("app.core.auth.SessionLocal") as mock_session_class:
                        mock_session = MagicMock()
                        mock_session_class.return_value = mock_session

                        # Mock query returning no user
                        mock_result = Mock()
                        mock_result.scalar_one_or_none.return_value = None
                        mock_session.execute.return_value = mock_result

                        result = await get_current_user_id(authorization="Bearer valid-token")

                        assert result is None
                        mock_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_get_current_user_id_database_error(mock_public_key):
    """Test that database errors return None gracefully (JWKS)."""
    with patch("app.core.auth.settings") as mock_settings:
        mock_settings.SUPABASE_URL = "https://test.supabase.co"

        with patch("app.core.auth.jwt.get_unverified_header") as mock_get_header:
            mock_get_header.return_value = {"kid": "test-kid-123", "alg": "ES256"}

            with patch("app.core.auth.auth_cache.get_key", new_callable=AsyncMock) as mock_get_key:
                mock_get_key.return_value = mock_public_key

                with patch("app.core.auth.jwt.decode") as mock_decode:
                    mock_decode.return_value = {
                        "sub": "test-auth-uid",
                        "exp": 9999999999
                    }

                    with patch("app.core.auth.SessionLocal") as mock_session_class:
                        mock_session = MagicMock()
                        mock_session_class.return_value = mock_session

                        # Mock database error
                        mock_session.execute.side_effect = Exception("Database connection failed")

                        result = await get_current_user_id(authorization="Bearer valid-token")

                        assert result is None
                        mock_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_require_current_user_id_with_valid_token(mock_user):
    """Test require_current_user_id with valid token returns user_id."""
    with patch("app.core.auth.get_current_user_id") as mock_get_user:
        mock_get_user.return_value = mock_user.id

        result = await require_current_user_id(authorization="Bearer valid-token")

        assert result == mock_user.id


@pytest.mark.asyncio
async def test_require_current_user_id_raises_401():
    """Test that require_current_user_id raises 401 when no token."""
    with patch("app.core.auth.get_current_user_id") as mock_get_user:
        mock_get_user.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await require_current_user_id(authorization=None)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Authentication required"
        assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}


@pytest.mark.asyncio
async def test_require_current_user_id_raises_401_invalid_token():
    """Test that require_current_user_id raises 401 for invalid token."""
    with patch("app.core.auth.get_current_user_id") as mock_get_user:
        mock_get_user.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await require_current_user_id(authorization="Bearer invalid")

        assert exc_info.value.status_code == 401
