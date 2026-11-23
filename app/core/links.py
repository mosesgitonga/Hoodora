"""Spotting links in text people write (decision L.2).

Someone new to an area may not put links in comments, and nobody may in the first
few messages of a chat they started: links are how most scams in a neighbourhood
app reach people. This errs towards finding a link. A false alarm costs a
rewording; a missed one can cost someone money.
"""

from __future__ import annotations

import re

# A scheme, "www.", a well-known short link, or a word ending in a common domain
# suffix, with or without a path. The suffix list leans on what Kenyans meet:
# .co.ke and .ke, the big generic ones, and those favoured by link shorteners.
_LINK = re.compile(
    r"""
    (?:\b[a-z][a-z0-9+.-]*://\S+)                          # http://, https://, ftp://
    | (?:\bwww\.\S+)                                       # www.example
    | (?:\b(?:wa\.me|t\.me|bit\.ly|tinyurl\.com|goo\.gl)\b)  # short links and chat invites
    | (?:\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.
        (?:co\.ke|or\.ke|go\.ke|ac\.ke|ke|com|net|org|info|biz|io|me|ly|xyz|link
           |app|site|online|top|click|shop|store|live|club|tk|ml|ga|cf|gq)
        \b(?:/\S*)?)
    """,
    re.IGNORECASE | re.VERBOSE,
)


def contains_link(text: str | None) -> bool:
    return bool(text) and _LINK.search(text or "") is not None
