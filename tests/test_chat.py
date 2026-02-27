"""Tests for corphish.chat."""

from unittest.mock import MagicMock, patch

import pytest

from corphish.chat import build_service, create_space, send_message


def test_build_service_calls_discovery():
    mock_creds = MagicMock()
    with patch("corphish.chat.build") as mock_build:
        mock_build.return_value = MagicMock()
        build_service(mock_creds)
    mock_build.assert_called_once_with("chat", "v1", credentials=mock_creds)


def test_build_service_returns_resource():
    mock_creds = MagicMock()
    mock_resource = MagicMock()
    with patch("corphish.chat.build", return_value=mock_resource):
        result = build_service(mock_creds)
    assert result is mock_resource


def test_create_space_default_display_name():
    mock_service = MagicMock()
    mock_service.spaces().create().execute.return_value = {
        "name": "spaces/abc123",
        "displayName": "Corphish",
    }
    create_space(mock_service)
    mock_service.spaces().create.assert_called_with(
        body={"displayName": "Corphish", "spaceType": "SPACE"}
    )


def test_create_space_custom_display_name():
    mock_service = MagicMock()
    mock_service.spaces().create().execute.return_value = {
        "name": "spaces/abc123",
        "displayName": "My Space",
    }
    create_space(mock_service, display_name="My Space")
    mock_service.spaces().create.assert_called_with(
        body={"displayName": "My Space", "spaceType": "SPACE"}
    )


def test_create_space_returns_response():
    mock_service = MagicMock()
    expected = {"name": "spaces/abc123", "displayName": "Corphish"}
    mock_service.spaces().create().execute.return_value = expected
    result = create_space(mock_service)
    assert result == expected


def test_send_message_calls_api():
    mock_service = MagicMock()
    mock_service.spaces().messages().create().execute.return_value = {
        "name": "spaces/abc123/messages/1"
    }
    send_message(mock_service, "spaces/abc123", "Hello!")
    mock_service.spaces().messages().create.assert_called_with(
        parent="spaces/abc123", body={"text": "Hello!"}
    )


def test_send_message_returns_response():
    mock_service = MagicMock()
    expected = {"name": "spaces/abc123/messages/1"}
    mock_service.spaces().messages().create().execute.return_value = expected
    result = send_message(mock_service, "spaces/abc123", "Hello!")
    assert result == expected


def test_send_message_empty_space_name_raises():
    mock_service = MagicMock()
    with pytest.raises(ValueError, match="space_name must not be empty"):
        send_message(mock_service, "", "Hello!")


