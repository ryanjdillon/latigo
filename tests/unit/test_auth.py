import pytest
from unittest import mock
import typing

from latigo.auth import fetch_access_token, create_auth_session

VALID_TOKEN: typing.Dict[str, typing.Union[str, int]] = {
    "accessToken": "dummy-token",
    "refreshToken": "dummy-refresh",
    "tokenType": "dummy-type",
    "expiresIn": 1000,
}
BAD_TOKEN: typing.Dict[str, typing.Union[str, int]] = {}


@mock.patch("latigo.auth.adal.AuthenticationContext", autospec=True)
@pytest.mark.parametrize(
    "token,expected_oath_token",
    [
        # When keys provided, remapped to `oath` key strings
        (
            VALID_TOKEN,
            {
                "access_token": "dummy-token",
                "refresh_token": "dummy-refresh",
                "token_type": "dummy-type",
                "expires_in": 1000,
            },
        ),
        # Single key provided, returns `oath` defaults for other keys
        (
            {"accessToken": "dummy-token"},
            {
                "access_token": "dummy-token",
                "refresh_token": "",
                "token_type": "Bearer",
                "expires_in": 0,
            },
        ),
        # Empty token provided, get `oath` token of `None`
        (BAD_TOKEN, None),
    ],
)
def test_fetch_access_token_functioning_adal(
    MockAuthenticationContext, auth_config, token, expected_oath_token
):
    """
    Test that Adal auth token values result in expected OAuth tokens
    """

    mock_auth_context = MockAuthenticationContext(
        authority="https://dummy-authority", validate_authority=None, api_version=None
    )

    mock_auth_context.acquire_token_with_client_credentials.return_value = token
    oath_token = fetch_access_token(auth_config)
    assert oath_token == expected_oath_token


@mock.patch("latigo.auth.adal.AuthenticationContext", autospec=True)
def test_fetch_access_token_malfunctioning_adal(MockAuthenticationContext, auth_config):
    """
    Test that when adal methods error, Exception is raises
    """
    # Context retrieval success, token retrieval method errors
    mock_auth_context = MockAuthenticationContext(
        authority="https://dummy-authority", validate_authority=None, api_version=None
    )
    mock_auth_context.acquire_token_with_client_credentials.side_effect = Exception
    with pytest.raises(Exception):
        fetch_access_token(auth_config)

    # Context generation errors
    MockAuthenticationContext.side_effect = Exception
    with pytest.raises(Exception):
        fetch_access_token(auth_config)


@mock.patch("latigo.auth.OAuth2Session", autospec=True)
@mock.patch("latigo.auth.adal.AuthenticationContext", autospec=True)
def test_create_auth_session(MockAuthenticationContext, MockOAuth2Session, auth_config):
    """
    Test that OAuth session creation logic
    1. A valid token, and successful session creation returns the session
    2. A valid token, and failed session creation returns `None`.
    3. An invalid token, returns `None`
    """
    mock_auth_context = MockAuthenticationContext(
        authority="https://dummy-authority", validate_authority=None, api_version=None
    )

    # OAuth token retrieved, session created and returns
    MockOAuth2Session.side_effect = "valid-session"
    mock_auth_context.acquire_token_with_client_credentials.return_value = VALID_TOKEN
    assert create_auth_session(auth_config)

    # OAuth token retrieved, session creation throws exception, return session of `None`
    MockOAuth2Session.side_effect = Exception
    mock_auth_context.acquire_token_with_client_credentials.return_value = BAD_TOKEN
    assert create_auth_session(auth_config) is None

    # OAuth token not retrieved, return session of `None`
    mock_auth_context.acquire_token_with_client_credentials.return_value = BAD_TOKEN
    assert create_auth_session(auth_config) is None
