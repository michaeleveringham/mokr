from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any


class RouteStack:
    """Shared newest-first request callback stack.

    Both backends retain their native request objects but use this dispatcher
    so callback ordering and the default-release behavior cannot drift.
    """

    def __init__(self, default: Callable[[Any], Any] | None = None) -> None:
        self._callbacks: list[Callable[[Any], Any]] = []
        self._default = default

    @property
    def callbacks(self) -> list[Callable[[Any], Any]]:
        return self._callbacks

    def add(self, callback: Callable[[Any], Any]) -> None:
        if callback in self._callbacks:
            self._callbacks.remove(callback)
        self._callbacks.insert(0, callback)

    def remove(self, callback: Callable[[Any], Any]) -> bool:
        try:
            self._callbacks.remove(callback)
        except ValueError:
            return False
        return True

    async def dispatch(self, request: Any) -> Any:
        result: Any = request
        for callback in self._callbacks:
            if result is None or getattr(request, "is_handled", False):
                break
            result = callback(result)
            if inspect.isawaitable(result):
                result = await result
        if not getattr(request, "is_handled", False) and self._default:
            result = self._default(request)
            if inspect.isawaitable(result):
                await result
        return result
