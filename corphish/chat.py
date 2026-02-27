"""Google Chat API operations."""

from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


def build_service(creds: Credentials) -> Any:
    """Builds a Google Chat API service resource.

    Args:
        creds: Valid OAuth2 credentials authorised for Chat API scopes.

    Returns:
        A googleapiclient Resource for the Chat v1 API.
    """
    return build("chat", "v1", credentials=creds)


def create_space(service: Any, display_name: str = "Corphish") -> dict:
    """Creates a new Google Chat space.

    Args:
        service: A Chat API service resource from build_service().
        display_name: Human-readable name for the space.

    Returns:
        The API response dict, including the space's resource name under
        the key "name" (e.g. "spaces/abc123").
    """
    return (
        service.spaces()
        .create(body={"displayName": display_name, "spaceType": "SPACE"})
        .execute()
    )


def send_message(service: Any, space_name: str, text: str) -> dict:
    """Sends a text message to a Google Chat space.

    Args:
        service: A Chat API service resource from build_service().
        space_name: The resource name of the space (e.g. "spaces/abc123").
        text: The message text to send.

    Returns:
        The API response dict for the created message.

    Raises:
        ValueError: If space_name is empty.
    """
    if not space_name:
        raise ValueError("space_name must not be empty")
    return (
        service.spaces()
        .messages()
        .create(parent=space_name, body={"text": text})
        .execute()
    )
