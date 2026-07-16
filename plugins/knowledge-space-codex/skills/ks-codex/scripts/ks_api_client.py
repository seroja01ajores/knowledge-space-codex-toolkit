#!/usr/bin/env python3
"""Reusable official-API client helpers for KS automation scripts.

The module intentionally stores no stand URL, credentials, tokens, cookies, or
project UUIDs. Configure it with environment variables or explicit arguments.
"""

from __future__ import annotations

import getpass
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import requests

from ks_secret_safety import is_sensitive_key, redact_text, semantic_secret_value_keys


class KSAPIError(RuntimeError):
    """Raised when KS returns an HTTP or JSON-level error."""


class KSAPIUncertainResultError(KSAPIError):
    """Raised when a request may have reached KS but no reliable result arrived."""


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        semantic_keys = semantic_secret_value_keys(value)
        for key, item in value.items():
            if is_sensitive_key(key) or key in semantic_keys:
                redacted[key] = "<redacted>"
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def unwrap_list(body: Any) -> list[Any]:
    """Return the first common KS list payload from a response body."""
    if isinstance(body, list):
        return body
    if not isinstance(body, dict):
        return []
    for key in ("data", "items", "objects", "list", "models", "dashboards", "publications", "gantts"):
        value = body.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = unwrap_list(value)
            if nested:
                return nested
    return []


def unwrap_entity(body: Any, *preferred_keys: str) -> dict[str, Any]:
    """Return a KS entity object from common response wrappers."""
    if isinstance(body, dict):
        for key in preferred_keys:
            value = body.get(key)
            if isinstance(value, dict):
                return value
        data = body.get("data")
        if isinstance(data, dict):
            for key in preferred_keys:
                value = data.get(key)
                if isinstance(value, dict):
                    return value
            return data
        return body
    raise KSAPIError("Expected object response, got non-object payload")


@dataclass
class KSClient:
    base_url: str
    login_name: str | None = None
    password: str | None = None
    project_uuid: str | None = None
    token: str | None = None
    timeout: int = 90

    def __post_init__(self) -> None:
        if (
            not isinstance(self.base_url, str)
            or self.base_url != self.base_url.strip()
            or any(ord(character) < 32 or ord(character) == 127 for character in self.base_url)
        ):
            raise KSAPIError("KS base URL is invalid")
        try:
            parsed = urlsplit(self.base_url)
            _port = parsed.port
        except (TypeError, ValueError) as exc:
            raise KSAPIError("KS base URL is invalid") from exc
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or "?" in self.base_url
            or "#" in self.base_url
            or "\\" in parsed.path
            or "%" in parsed.path
            or ";" in parsed.path
            or "//" in parsed.path
            or any(part in {".", ".."} for part in parsed.path.split("/"))
            or any(character.isspace() for character in parsed.path)
        ):
            raise KSAPIError(
                "KS base URL must be an http(s) URL without credentials, query, or fragment"
            )
        self.base_url = self.base_url.rstrip("/")
        self.session = requests.Session()
        if self.token:
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})

    @classmethod
    def from_env(cls, *, require_project: bool = True, prompt_password: bool = False) -> "KSClient":
        base_url = os.environ.get("KS_BASE_URL")
        if not base_url:
            raise KSAPIError("KS_BASE_URL is required, for example https://<host>/api")

        project_uuid = os.environ.get("KS_PROJECT_UUID")
        if require_project and not project_uuid:
            raise KSAPIError("KS_PROJECT_UUID is required for project-scoped KS work")

        login_name = os.environ.get("KS_LOGIN")
        password = os.environ.get("KS_PASSWORD")
        token = os.environ.get("KS_TOKEN")

        if not token and not login_name:
            raise KSAPIError("Set KS_TOKEN or KS_LOGIN/KS_PASSWORD")
        if not token and not password and prompt_password:
            password = getpass.getpass("KS password: ")

        return cls(
            base_url=base_url,
            login_name=login_name,
            password=password,
            project_uuid=project_uuid,
            token=token,
        )

    def login(self) -> str:
        """Authenticate with /auth/login unless a token is already configured."""
        if self.token:
            return self.token
        if not self.login_name:
            raise KSAPIError("KS login is missing")
        if not self.password:
            raise KSAPIError("KS password is missing; set KS_PASSWORD or enable prompt_password")

        body = self.post(
            "/auth/login",
            {"login": self.login_name, "password": self.password},
            project=False,
            auth=False,
        )
        token = (
            body.get("token")
            or body.get("accessToken")
            or body.get("data", {}).get("token")
            or body.get("data", {}).get("accessToken")
        )
        if not token:
            raise KSAPIError("Login succeeded but no token/accessToken was returned")
        self.token = token
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        return token

    def headers(self, *, project: bool = True) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-Lang": "ru_RU",
            "X-Project-Locales": "ru_RU",
        }
        if project:
            if not self.project_uuid:
                raise KSAPIError("Project-scoped call requires KS_PROJECT_UUID")
            headers["X-Project-UUID"] = self.project_uuid
        return headers

    def post(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        project: bool = True,
        auth: bool = True,
        ok_empty: bool = True,
    ) -> Any:
        if auth and not self.token:
            self.login()
        endpoint = "/" + path.lstrip("/")
        try:
            response = self.session.post(
                self.base_url + endpoint,
                json=payload or {},
                headers=self.headers(project=project),
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            detail = redact_text(
                str(exc),
                (self.password or "", self.token or ""),
            )[:1000]
            raise KSAPIUncertainResultError(
                f"{endpoint}: transport failure; request result is uncertain: {detail}"
            ) from exc
        if not 200 <= response.status_code < 300:
            detail = redact_text(
                response.text if response.text else "",
                (self.password or "", self.token or ""),
            )[:1000]
            raise KSAPIError(f"{endpoint}: HTTP {response.status_code}: {detail}")
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = redact_text(
                response.text if response.text else "",
                (self.password or "", self.token or ""),
            )[:1000]
            raise KSAPIError(f"{endpoint}: HTTP {response.status_code}: {detail}") from exc

        try:
            body = response.json() if response.text else {}
        except (ValueError, requests.RequestException) as exc:
            detail = redact_text(
                response.text if response.text else "",
                (self.password or "", self.token or ""),
            )[:1000]
            raise KSAPIUncertainResultError(
                f"{endpoint}: invalid JSON response; request result is uncertain: {detail}"
            ) from exc
        if isinstance(body, dict) and "error" in body:
            detail = redact_text(
                json.dumps(_redact(body["error"]), ensure_ascii=False),
                (self.password or "", self.token or ""),
            )
            raise KSAPIError(f"{endpoint}: {detail}")
        if not ok_empty and body in ({}, [], None):
            raise KSAPIError(f"{endpoint}: empty response")
        return body

    def get_by_id(self, entity: str, uuid: str, *, preferred_key: str | None = None) -> dict[str, Any]:
        body = self.post(f"/{entity}/get-by-id", {"UUID": uuid, "uuid": uuid}, ok_empty=False)
        return unwrap_entity(body, preferred_key or entity.rstrip("s"))

    def update_raw(self, entity: str, value: dict[str, Any]) -> Any:
        return self.post(f"/{entity}/update", value, ok_empty=True)

    def redacted_diagnostic(self) -> dict[str, Any]:
        return {
            "baseUrl": redact_text(
                self.base_url,
                (self.password or "", self.token or ""),
            ),
            "projectUuid": self.project_uuid or "<none>",
            "login": self.login_name or "<token-auth>",
            "hasToken": bool(self.token),
            "timeout": self.timeout,
        }


if __name__ == "__main__":
    client = KSClient.from_env(require_project=False)
    print(json.dumps(client.redacted_diagnostic(), ensure_ascii=False, indent=2))
