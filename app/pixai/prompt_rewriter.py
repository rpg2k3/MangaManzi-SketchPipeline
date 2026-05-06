"""Whitelist-only booru-tag normalizer for PixAI positive prompts.

The earlier mechanical rewriter was inventing fake tokens like
`full_body_figure`, `single_figure`, `centered_composition`. Booru models
attend to *trained* vocabulary; underscoring an unrecognized phrase
turns it into noise rather than a meaningful tag.

This rewriter is conservative: it only normalizes tokens that match a
known-booru whitelist. Everything else passes through unchanged
(spaces preserved, original case preserved).
"""

import re

_WS_OR_HYPHEN = re.compile(r"[\s\-]+")

# Tags we know live in Danbooru/Illustrious training vocabulary AND are
# relevant to our pipeline. Anything not in here passes through verbatim.
KNOWN_BOORU_TAGS: set[str] = {
    # Subject counts
    "1girl", "1boy", "1child",
    "solo",
    # Composition / framing
    "full_body", "looking_at_viewer",
    # Pose family
    "contrapposto",
    # Quality boosters (PixAI Booster equivalents)
    "masterpiece", "best_quality", "amazing_quality", "very_aesthetic", "absurdres",
}


def _normalize(token: str) -> str:
    return _WS_OR_HYPHEN.sub("_", token.strip().lower())


def to_booru(text: str | None) -> str | None:
    """Comma-tokenize, normalize whitelist matches, pass everything else
    through unchanged.
    """
    if text is None:
        return None
    if not text:
        return text
    out: list[str] = []
    for raw in text.split(","):
        stripped = raw.strip()
        if not stripped:
            continue
        normalized = _normalize(stripped)
        if normalized in KNOWN_BOORU_TAGS:
            out.append(normalized)
        else:
            out.append(stripped)
    return ", ".join(out)
