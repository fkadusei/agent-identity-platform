"""Tiny fake HTTP client for testing without a live server."""
from __future__ import annotations

from typing import Any


class FakeResponse:
    def __init__(self, status_code: int = 200, json_data: Any = None, text: str = ""):
        self.status_code = status_code
        self._json = {} if json_data is None else json_data
        self.text = text

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    """Records calls and returns a canned response (or raises)."""

    def __init__(self, response: FakeResponse | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[dict] = []

    def post(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response
