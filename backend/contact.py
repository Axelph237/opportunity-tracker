"""The contact block at the top of a resume: who this is and how to reach them.

One record for the whole install, not one per draft. A name and an email do
not change with the job being applied for, and asking for them again on every
new resume is how a resume goes out reading "Your Name".

Stored as a JSON settings row rather than a table, the way the other
structured values in this project are, because there is exactly one of it and
nothing joins against its parts.
"""

from __future__ import annotations

import json
from typing import Any

from database import get_setting, set_setting

SETTING_KEY = "resume_contact"

MAX_FIELD = 200
MAX_LINKS = 6

BLANK: dict[str, Any] = {
    "name": "",
    "location": "",
    "email": "",
    "phone": "",
    "links": [],
}


def _text(value: Any) -> str:
    return str(value).strip()[:MAX_FIELD] if isinstance(value, (str, int, float)) else ""


def _links(value: Any) -> list[dict[str, str]]:
    """Label and url pairs, dropping any that would print as an empty link."""
    if not isinstance(value, list):
        return []
    links = []
    for item in value[:MAX_LINKS]:
        if not isinstance(item, dict):
            continue
        url = _text(item.get("url"))
        if not url:
            continue
        # A link with no label prints as its own address, which is what a
        # resume does with a bare github url anyway.
        links.append({"label": _text(item.get("label")) or url, "url": url})
    return links


def normalize(payload: Any) -> dict[str, Any]:
    """Every field rebuilt from scratch, so nothing unrecognised is stored."""
    data = payload if isinstance(payload, dict) else {}
    return {
        "name": _text(data.get("name")),
        "location": _text(data.get("location")),
        "email": _text(data.get("email")),
        "phone": _text(data.get("phone")),
        "links": _links(data.get("links")),
    }


def get_contact() -> dict[str, Any]:
    stored = get_setting(SETTING_KEY)
    if not stored:
        return {**BLANK}
    try:
        return normalize(json.loads(stored))
    except (ValueError, TypeError):
        # A row that will not parse is a row nobody can fix from the
        # interface, so it reads as unset rather than taking the page down.
        return {**BLANK}


def save_contact(payload: Any) -> dict[str, Any]:
    contact = normalize(payload)
    set_setting(SETTING_KEY, json.dumps(contact))
    return contact


def is_filled(contact: dict[str, Any]) -> bool:
    """Whether there is anything here worth printing."""
    return bool(
        contact.get("name")
        or contact.get("email")
        or contact.get("phone")
        or contact.get("location")
        or contact.get("links")
    )
