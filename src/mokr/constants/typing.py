from typing import Literal


LIFECYCLE_EVENTS = Literal[
    "load",
    "domcontentloaded",
    "networkidle",
    "networkalmostidle",
]

HTTP_METHODS = Literal[
    "GET",
    "POST",
    "OPTIONS",
    "HEAD",
    "PUT",
    "PATCH",
    "DELETE",
]

HTTP_CACHE_TYPES = Literal[
    "default",
    "no-store",
    "reload",
    "no-cache",
    "force-cache",
    "only-if-cache",
]

REFERRER_POLICIES = Literal[
    "no-referrer",
    "no-referrer-when-downgrade",
    "same-origin",
    "origin",
    "strict-origin",
    "origin-when-cross-origin",
    "strict-origin-when-cross-origin",
    "unsafe-url",
]
