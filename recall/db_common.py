"""Helpers shared by the SQLite and Postgres stores."""
import re
import uuid

_WIKI_RE = re.compile(r'\[\[([^\[\]]+)\]\]')


def new_id() -> str:
    return str(uuid.uuid4())


def extract_wikilinks(content_md: str) -> list:
    """Return unique [[title]] anchors found in content_md, preserving order."""
    if not content_md:
        return []
    seen = set()
    anchors = []
    for match in _WIKI_RE.findall(content_md):
        anchor = match.strip()
        if anchor and anchor not in seen:
            seen.add(anchor)
            anchors.append(anchor)
    return anchors
