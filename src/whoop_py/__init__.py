from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, time, timedelta
from pathlib import Path
from time import time as now
from typing import Any
from urllib.parse import parse_qs, urlparse

from authlib.common.urls import extract_params
from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.requests_client import OAuth2Session


AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2"
REQUEST_URL = "https://api.prod.whoop.com/developer"


def _auth_password_json(_client, _method, uri, headers, body):
    body = json.dumps(dict(extract_params(body)))
    headers["Content-Type"] = "application/json"
    return uri, headers, body


class WhoopClient:
    """Low-level WHOOP API client wrapping an OAuth2 session."""

    TOKEN_ENDPOINT_AUTH_METHOD = "password_json"  # noqa

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        authenticate: bool = True,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str | None = None,
        scope: str | None = None,
        token: dict[str, Any] | None = None,
    ):
        self._username = username
        self._password = password
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._scope = scope

        if client_id or client_secret or redirect_uri or scope or token:
            self.session = OAuth2Session(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope=scope,
                token=token,
                token_endpoint_auth_method="client_secret_post",
            )
        else:
            self.session = OAuth2Session(
                token_endpoint_auth_method=self.TOKEN_ENDPOINT_AUTH_METHOD,
            )
            self.session.register_client_auth_method(
                (self.TOKEN_ENDPOINT_AUTH_METHOD, _auth_password_json)
            )

        self.user_id = ""

        if authenticate and self._username and self._password:
            self.authenticate()

    def __enter__(self) -> WhoopClient:
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def __str__(self) -> str:
        return f"WhoopClient({self.user_id if self.user_id else '<Unauthenticated>'})"

    def close(self) -> None:
        self.session.close()

    def create_authorization_url(self, state: str | None = None, scope: str | None = None, **kwargs: Any) -> tuple[str, str]:
        return self.session.create_authorization_url(
            url=f"{AUTH_URL}/auth",
            state=state,
            scope=scope or self._scope,
            **kwargs,
        )

    def fetch_token(self, code: str | None = None, authorization_response: str | None = None, **kwargs: Any) -> dict[str, Any]:
        return self.session.fetch_token(
            url=f"{AUTH_URL}/token",
            code=code,
            authorization_response=authorization_response,
            client_id=self._client_id,
            client_secret=self._client_secret,
            **kwargs,
        )

    def refresh_access_token(self, refresh_token: str, scope: str = "offline", **kwargs: Any) -> dict[str, Any]:
        return self.session.refresh_token(
            url=f"{AUTH_URL}/token",
            refresh_token=refresh_token,
            scope=scope,
            client_id=self._client_id,
            client_secret=self._client_secret,
            **kwargs,
        )

    def authenticate(self, **kwargs) -> None:
        if not self._username or not self._password:
            raise ValueError("Username/password not set. Use create_authorization_url() + fetch_token() for OAuth 2.0.")
        try:
            self.session.fetch_token(
                url=f"{AUTH_URL}/token",
                username=self._username,
                password=self._password,
                grant_type="password",
                **kwargs,
            )
        except OAuthError as exc:
            raise RuntimeError(
                "WHOOP rejected username/password authentication. Use OAuth 2.0 authorization-code flow."
            ) from exc

        if not self.user_id:
            self.user_id = str(self.session.token.get("user", {}).get("id", ""))

    def is_authenticated(self) -> bool:
        return bool(self.session.token and self.session.token.get("access_token"))

    def get_profile(self) -> dict[str, Any]:
        return self._make_request("GET", "v2/user/profile/basic")

    def get_body_measurement(self) -> dict[str, Any]:
        return self._make_request("GET", "v2/user/measurement/body")

    def get_cycle_by_id(self, cycle_id: str) -> dict[str, Any]:
        return self._make_request("GET", f"v2/cycle/{cycle_id}")

    def get_cycle_collection(self, start_date: str | None = None, end_date: str | None = None) -> list[dict[str, Any]]:
        start, end = self._format_dates(start_date, end_date)
        return self._make_paginated_request("GET", "v2/cycle", params={"start": start, "end": end, "limit": 25})

    def get_recovery_for_cycle(self, cycle_id: str) -> dict[str, Any]:
        return self._make_request("GET", f"v2/cycle/{cycle_id}/recovery")

    def get_recovery_collection(self, start_date: str | None = None, end_date: str | None = None) -> list[dict[str, Any]]:
        start, end = self._format_dates(start_date, end_date)
        return self._make_paginated_request("GET", "v2/recovery", params={"start": start, "end": end, "limit": 25})

    def get_current_recovery(self) -> dict[str, Any] | None:
        response = self._make_request("GET", "v2/recovery", params={"limit": 1})
        records = response.get("records", [])
        return records[0] if records else None

    def get_sleep_by_id(self, sleep_id: str) -> dict[str, Any]:
        return self._make_request("GET", f"v2/activity/sleep/{sleep_id}")

    def get_sleep_collection(self, start_date: str | None = None, end_date: str | None = None) -> list[dict[str, Any]]:
        start, end = self._format_dates(start_date, end_date)
        return self._make_paginated_request("GET", "v2/activity/sleep", params={"start": start, "end": end, "limit": 25})

    def get_sleep_stream(self, sleep_id: str, types: list[str] | None = None) -> dict[str, Any]:
        params = {"types": types} if types else {}
        return self._make_request("GET", f"v2/activity/sleep/{sleep_id}/stream", params=params)

    def get_workout_by_id(self, workout_id: str) -> dict[str, Any]:
        return self._make_request("GET", f"v2/activity/workout/{workout_id}")

    def get_workout_collection(self, start_date: str | None = None, end_date: str | None = None) -> list[dict[str, Any]]:
        start, end = self._format_dates(start_date, end_date)
        return self._make_paginated_request("GET", "v2/activity/workout", params={"start": start, "end": end, "limit": 25})

    def _make_paginated_request(self, method: str, url_slug: str, **kwargs) -> list[dict[str, Any]]:
        params = kwargs.pop("params", {})
        records: list[dict[str, Any]] = []
        while True:
            response = self._make_request(method, url_slug, params=params, **kwargs)
            records += response.get("records", [])
            if next_token := response.get("next_token"):
                params["nextToken"] = next_token
            else:
                break
        return records

    def _make_request(self, method: str, url_slug: str, **kwargs: Any) -> dict[str, Any]:
        response = self.session.request(method=method, url=f"{REQUEST_URL}/{url_slug}", **kwargs)
        response.raise_for_status()
        return response.json()

    def _format_dates(self, start_date: str | None, end_date: str | None) -> tuple[str, str]:
        end = datetime.combine(
            datetime.fromisoformat(end_date) if end_date else datetime.today(), time.max
        )
        start = datetime.combine(
            datetime.fromisoformat(start_date) if start_date else datetime.today() - timedelta(days=6),
            time.min,
        )
        if start > end:
            raise ValueError(f"Start datetime greater than end datetime: {start} > {end}")
        return start.isoformat() + "Z", end.isoformat(timespec="seconds") + "Z"


class WhoopAPI:
    """WHOOP API client with OAuth token persistence and interactive auth flow."""

    DEFAULT_SCOPES = {"offline", "read:sleep", "read:recovery", "read:workout", "read:profile", "read:body_measurement"}
    DEFAULT_TOKEN_PATH = Path(".whoop_token.json")
    TOKEN_EXPIRY_SKEW_SECONDS = 60

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str | None = None,
        scopes: set[str] | None = None,
        token_path: Path | str | None = None,
    ):
        self.client_id = client_id or os.getenv("CLIENT_ID")
        self.client_secret = client_secret or os.getenv("CLIENT_SECRET")
        self.redirect_uri = redirect_uri or os.getenv("REDIRECT_URI")
        self.scopes = scopes or self.DEFAULT_SCOPES
        self.token_path = Path(token_path or self.DEFAULT_TOKEN_PATH)
        self.scope_string = " ".join(sorted(self.scopes))
        self._client: WhoopClient | None = None

        missing = [k for k, v in {"CLIENT_ID": self.client_id, "CLIENT_SECRET": self.client_secret, "REDIRECT_URI": self.redirect_uri}.items() if not v]
        if missing:
            raise ValueError(f"Missing required config: {', '.join(missing)}")

    def __enter__(self) -> WhoopAPI:
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def get_authenticated_client(self) -> WhoopClient:
        if self._client is not None:
            return self._client

        token = self._load_token()

        if token is None:
            print("No stored token found. Starting OAuth flow...")
            token = self._authorize_interactive()
            self._save_token(token)
        elif not self._has_required_scopes(token):
            print("Token missing required scopes. Re-authorizing...")
            token = self._authorize_interactive()
            self._save_token(token)
        elif self._is_token_expired(token):
            refresh_token = token.get("refresh_token")
            if refresh_token:
                try:
                    client = self._build_client(token=token)
                    token = client.refresh_access_token(refresh_token=refresh_token, scope=self.scope_string)
                    self._save_token(token)
                except Exception as exc:
                    print(f"Token refresh failed: {exc}. Re-authorizing...")
                    token = self._authorize_interactive()
                    self._save_token(token)
            else:
                print("No refresh token. Re-authorizing...")
                token = self._authorize_interactive()
                self._save_token(token)

        self._client = self._build_client(token=token)
        return self._client

    def get_profile(self) -> dict[str, Any]:
        return self.get_authenticated_client().get_profile()

    def get_body_measurement(self) -> dict[str, Any]:
        return self.get_authenticated_client().get_body_measurement()

    def get_cycle_by_id(self, cycle_id: str) -> dict[str, Any]:
        return self.get_authenticated_client().get_cycle_by_id(cycle_id)

    def get_cycle_collection(self, start_date: str | None = None, end_date: str | None = None) -> list[dict[str, Any]]:
        return self.get_authenticated_client().get_cycle_collection(start_date, end_date)

    def get_recovery_for_cycle(self, cycle_id: str) -> dict[str, Any]:
        return self.get_authenticated_client().get_recovery_for_cycle(cycle_id)

    def get_recovery_collection(self, start_date: str | None = None, end_date: str | None = None) -> list[dict[str, Any]]:
        return self.get_authenticated_client().get_recovery_collection(start_date, end_date)

    def get_current_recovery(self) -> dict[str, Any] | None:
        return self.get_authenticated_client().get_current_recovery()

    def get_sleep_by_id(self, sleep_id: str) -> dict[str, Any]:
        return self.get_authenticated_client().get_sleep_by_id(sleep_id)

    def get_sleep_collection(self, start_date: str | None = None, end_date: str | None = None) -> list[dict[str, Any]]:
        return self.get_authenticated_client().get_sleep_collection(start_date, end_date)

    def get_sleep_stream(self, sleep_id: str, types: list[str] | None = None) -> dict[str, Any]:
        return self.get_authenticated_client().get_sleep_stream(sleep_id, types)

    def get_workout_by_id(self, workout_id: str) -> dict[str, Any]:
        return self.get_authenticated_client().get_workout_by_id(workout_id)

    def get_workout_collection(self, start_date: str | None = None, end_date: str | None = None) -> list[dict[str, Any]]:
        return self.get_authenticated_client().get_workout_collection(start_date, end_date)

    def _build_client(self, token: dict | None = None) -> WhoopClient:
        return WhoopClient(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=self.redirect_uri,
            scope=self.scope_string,
            token=token,
            authenticate=False,
        )

    def _load_token(self) -> dict | None:
        if not self.token_path.exists():
            return None
        return json.loads(self.token_path.read_text(encoding="utf-8"))

    def _save_token(self, token: dict) -> None:
        self.token_path.write_text(json.dumps(token, indent=2), encoding="utf-8")

    def _is_token_expired(self, token: dict) -> bool:
        expires_at = token.get("expires_at")
        return expires_at is None or float(expires_at) <= (now() + self.TOKEN_EXPIRY_SKEW_SECONDS)

    def _has_required_scopes(self, token: dict) -> bool:
        granted = set(str(token.get("scope", "")).strip().split())
        return bool(granted) and self.scopes.issubset(granted)

    def _authorize_interactive(self) -> dict:
        client = self._build_client()
        state = secrets.token_urlsafe(8)[:8]
        auth_url, _ = client.create_authorization_url(state=state)
        print("Open this URL and approve access:")
        print(auth_url)
        redirect_response = input("Paste the full redirect URL here: ").strip()
        parsed = urlparse(redirect_response)
        codes = parse_qs(parsed.query).get("code", [])
        if not codes:
            raise ValueError("Missing OAuth code in redirect URL.")
        return client.fetch_token(code=codes[0])


__all__ = ["WhoopClient", "WhoopAPI"]
