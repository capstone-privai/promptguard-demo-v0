from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


BASE_URL = os.environ.get("PROMPTGUARD_DAEMON_URL", "http://127.0.0.1:18765")


class TransportError(RuntimeError):
    pass


def request(method: str, route: str, payload: dict[str, Any] | None = None, timeout: float = 0.8) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + route,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise TransportError(str(exc)) from exc


def post(route: str, payload: dict[str, Any], timeout: float = 0.8) -> dict[str, Any]:
    return request("POST", route, payload, timeout)


def get(route: str, timeout: float = 0.8) -> dict[str, Any]:
    return request("GET", route, timeout=timeout)
