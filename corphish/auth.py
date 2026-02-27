"""OAuth2 credential lifecycle for Google APIs."""

from pathlib import Path
from typing import Callable, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/chat.spaces.create",
    "https://www.googleapis.com/auth/chat.messages.create",
    "https://www.googleapis.com/auth/chat.spaces.readonly",
]


def get_credentials(
    client_secret_path: Path,
    token_path: Path,
    flow_factory: Optional[Callable[[str, list[str]], InstalledAppFlow]] = None,
) -> Credentials:
    """Returns valid OAuth2 credentials for the Google Chat API.

    Loads cached credentials from token_path if available. Refreshes
    silently if expired. Runs a browser-based OAuth2 flow if no token
    exists yet.

    Args:
        client_secret_path: Path to the client_secret.json file downloaded
            from the Google Cloud Console.
        token_path: Path where the OAuth2 token is cached between runs.
        flow_factory: Optional callable used to construct the OAuth2 flow;
            injectable for testing. Defaults to InstalledAppFlow.from_client_secrets_file.

    Returns:
        Valid Credentials object authorised for SCOPES.

    Raises:
        FileNotFoundError: If client_secret_path does not exist.
    """
    if not client_secret_path.exists():
        raise FileNotFoundError(
            f"Client secret not found at {client_secret_path}.\n"
            "Download it from the Google Cloud Console:\n"
            "  APIs & Services → Credentials → OAuth 2.0 Client IDs → Download JSON\n"
            f"Then place it at {client_secret_path}"
        )

    creds = _load_token(token_path)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_token(creds, token_path)
        return creds

    # No usable token — run browser flow.
    factory = flow_factory or InstalledAppFlow.from_client_secrets_file
    flow = factory(str(client_secret_path), SCOPES)
    creds = flow.run_local_server(port=0)
    _save_token(creds, token_path)
    return creds


def _load_token(token_path: Path) -> Optional[Credentials]:
    """Loads credentials from token_path, or returns None if absent.

    Args:
        token_path: Path to the cached token file.

    Returns:
        Credentials if the file exists, None otherwise.
    """
    if not token_path.exists():
        return None
    return Credentials.from_authorized_user_file(str(token_path), SCOPES)


def _save_token(creds: Credentials, token_path: Path) -> None:
    """Saves credentials to token_path.

    Args:
        creds: The credentials to persist.
        token_path: Destination path for the token file.
    """
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
