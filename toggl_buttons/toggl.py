import base64
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib import error, request


API_BASE_URL = "https://api.track.toggl.com/api/v9"


class TogglAPIError(RuntimeError):
    pass


@dataclass
class TimeEntry:
    id: int
    workspace_id: int
    description: str
    project_id: int | None
    task_id: int | None
    tags: list[str]
    raw: dict[str, Any]

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "TimeEntry":
        return cls(
            id=int(payload["id"]),
            workspace_id=int(payload["workspace_id"]),
            description=payload.get("description") or "",
            project_id=payload.get("project_id"),
            task_id=payload.get("task_id"),
            tags=list(payload.get("tags") or []),
            raw=payload,
        )


class TogglClient:
    def __init__(self, api_token: str, user_agent: str):
        self.api_token = api_token.strip()
        if not self.api_token:
            raise ValueError("A Toggl API token is required.")
        self.user_agent = user_agent

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{API_BASE_URL}{path}"
        headers = {
            "Authorization": self._build_auth_header(),
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
        }
        data = None if payload is None else json.dumps(payload).encode()
        req = request.Request(url, data=data, headers=headers, method=method)

        try:
            with request.urlopen(req, timeout=30) as response:
                body = response.read().decode()
        except error.HTTPError as exc:
            body = exc.read().decode(errors="ignore")
            raise TogglAPIError(
                f"{method} {path} failed with {exc.code}: {body or exc.reason}"
            ) from exc
        except error.URLError as exc:
            raise TogglAPIError(f"{method} {path} failed: {exc.reason}") from exc

        if not body:
            return None

        return json.loads(body)

    def _build_auth_header(self) -> str:
        token = f"{self.api_token}:api_token".encode()
        encoded = base64.b64encode(token).decode()
        return f"Basic {encoded}"

    def get_me(self) -> dict[str, Any]:
        return self._request("GET", "/me")

    def get_default_workspace_id(self) -> int:
        me = self.get_me()
        workspace_id = me.get("default_workspace_id")
        if workspace_id is None:
            raise TogglAPIError(
                "No workspace_id was configured and Toggl did not return default_workspace_id."
            )
        return int(workspace_id)

    def get_current_time_entry(self) -> TimeEntry | None:
        payload = self._request("GET", "/me/time_entries/current")
        if payload in (None, "", {}):
            return None
        if payload == "null":
            return None
        if isinstance(payload, dict) and payload.get("data") is None and "id" not in payload:
            return None
        if isinstance(payload, dict) and "data" in payload and isinstance(payload["data"], dict):
            payload = payload["data"]
        if not payload:
            return None
        return TimeEntry.from_api(payload)

    def stop_time_entry(self, workspace_id: int, time_entry_id: int) -> Any:
        return self._request(
            "PATCH",
            f"/workspaces/{workspace_id}/time_entries/{time_entry_id}/stop",
        )

    def start_time_entry(
        self,
        *,
        workspace_id: int,
        description: str,
        created_with: str,
        project_id: int | None = None,
        task_id: int | None = None,
        tags: list[str] | None = None,
    ) -> TimeEntry:
        payload: dict[str, Any] = {
            "created_with": created_with,
            "description": description,
            "workspace_id": workspace_id,
            "duration": -1,
            "start": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "stop": None,
        }
        if project_id is not None:
            payload["project_id"] = project_id
        if task_id is not None:
            payload["task_id"] = task_id
        if tags:
            payload["tags"] = tags

        response = self._request(
            "POST",
            f"/workspaces/{workspace_id}/time_entries",
            payload=payload,
        )
        if isinstance(response, dict) and "data" in response and isinstance(response["data"], dict):
            response = response["data"]
        return TimeEntry.from_api(response)
