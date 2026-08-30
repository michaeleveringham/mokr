from __future__ import annotations

from typing import Any


def headers_to_dict(headers: list[dict[str, Any]]) -> dict[str, str]:
    """Convert BiDi header objects into mokr's lowercase header mapping."""
    return {
        header["name"].lower(): header["value"].get("value", "")
        for header in headers
    }
