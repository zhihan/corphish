"""Tests for corphish.auth."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from corphish.auth import get_credentials, SCOPES


def test_missing_client_secret_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="Client secret not found"):
        get_credentials(
            client_secret_path=tmp_path / "client_secret.json",
            token_path=tmp_path / "token.json",
        )


def test_missing_client_secret_error_includes_path(tmp_path):
    secret_path = tmp_path / "client_secret.json"
    with pytest.raises(FileNotFoundError, match=str(secret_path)):
        get_credentials(client_secret_path=secret_path, token_path=tmp_path / "token.json")


def test_valid_cached_token_returned(tmp_path):
    secret_path = tmp_path / "client_secret.json"
    secret_path.write_text("{}")
    token_path = tmp_path / "token.json"
    token_path.write_text("{}")

    mock_creds = MagicMock(spec=["valid", "expired", "refresh_token"])
    mock_creds.valid = True

    with patch("corphish.auth.Credentials.from_authorized_user_file", return_value=mock_creds):
        result = get_credentials(secret_path, token_path)

    assert result is mock_creds


def test_valid_token_does_not_call_flow(tmp_path):
    secret_path = tmp_path / "client_secret.json"
    secret_path.write_text("{}")
    token_path = tmp_path / "token.json"
    token_path.write_text("{}")

    mock_creds = MagicMock(spec=["valid", "expired", "refresh_token"])
    mock_creds.valid = True
    mock_factory = MagicMock()

    with patch("corphish.auth.Credentials.from_authorized_user_file", return_value=mock_creds):
        get_credentials(secret_path, token_path, flow_factory=mock_factory)

    mock_factory.assert_not_called()


def test_expired_token_is_refreshed(tmp_path):
    secret_path = tmp_path / "client_secret.json"
    secret_path.write_text("{}")
    token_path = tmp_path / "token.json"
    token_path.write_text("{}")

    mock_creds = MagicMock(spec=["valid", "expired", "refresh_token", "refresh", "to_json"])
    mock_creds.valid = False
    mock_creds.expired = True
    mock_creds.refresh_token = "refresh_tok"
    mock_creds.to_json.return_value = "{}"

    with patch("corphish.auth.Credentials.from_authorized_user_file", return_value=mock_creds):
        with patch("corphish.auth.Request"):
            result = get_credentials(secret_path, token_path)

    mock_creds.refresh.assert_called_once()
    assert result is mock_creds


def test_expired_token_is_saved_after_refresh(tmp_path):
    secret_path = tmp_path / "client_secret.json"
    secret_path.write_text("{}")
    token_path = tmp_path / "token.json"
    token_path.write_text("{}")

    mock_creds = MagicMock(spec=["valid", "expired", "refresh_token", "refresh", "to_json"])
    mock_creds.valid = False
    mock_creds.expired = True
    mock_creds.refresh_token = "refresh_tok"
    mock_creds.to_json.return_value = '{"refreshed": true}'

    with patch("corphish.auth.Credentials.from_authorized_user_file", return_value=mock_creds):
        with patch("corphish.auth.Request"):
            get_credentials(secret_path, token_path)

    assert token_path.read_text() == '{"refreshed": true}'


def test_no_token_runs_browser_flow(tmp_path):
    secret_path = tmp_path / "client_secret.json"
    secret_path.write_text("{}")
    token_path = tmp_path / "token.json"  # does not exist

    mock_creds = MagicMock(spec=["to_json"])
    mock_creds.to_json.return_value = "{}"
    mock_flow = MagicMock()
    mock_flow.run_local_server.return_value = mock_creds

    result = get_credentials(secret_path, token_path, flow_factory=lambda p, s: mock_flow)

    mock_flow.run_local_server.assert_called_once_with(port=0)
    assert result is mock_creds


def test_no_token_flow_saves_token(tmp_path):
    secret_path = tmp_path / "client_secret.json"
    secret_path.write_text("{}")
    token_path = tmp_path / "token.json"

    mock_creds = MagicMock(spec=["to_json"])
    mock_creds.to_json.return_value = '{"new": true}'
    mock_flow = MagicMock()
    mock_flow.run_local_server.return_value = mock_creds

    get_credentials(secret_path, token_path, flow_factory=lambda p, s: mock_flow)

    assert token_path.read_text() == '{"new": true}'


def test_flow_factory_receives_correct_args(tmp_path):
    secret_path = tmp_path / "client_secret.json"
    secret_path.write_text("{}")
    token_path = tmp_path / "token.json"

    mock_creds = MagicMock(spec=["to_json"])
    mock_creds.to_json.return_value = "{}"
    mock_flow = MagicMock()
    mock_flow.run_local_server.return_value = mock_creds

    captured = {}

    def factory(path, scopes):
        captured["path"] = path
        captured["scopes"] = scopes
        return mock_flow

    get_credentials(secret_path, token_path, flow_factory=factory)

    assert captured["path"] == str(secret_path)
    assert captured["scopes"] == SCOPES
