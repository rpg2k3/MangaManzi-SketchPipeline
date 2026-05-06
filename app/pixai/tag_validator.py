"""Booru tag validation — best-effort.

Underscored tokens in our positive prompts only carry attention weight if
they exist in the model's training vocabulary. Booru-trained checkpoints
(Illustrious, Pony, NoobAI) are trained on the Danbooru tag dictionary,
so a token like `mid_calf_lace_up_platform_boots` is only useful if that
exact tag was in training. Invented underscored phrases turn into noise.

This module:
- Caches the top-N Danbooru tags by post_count to data/danbooru_tags.csv
  (one tag per line: `name,post_count`).
- Validates the underscored tokens in a positive prompt against the cache,
  returning the list of unknown tokens for warning logs.
- Cache load is graceful: if the file is missing or unreadable, the
  validator returns an empty unknown-list (no false alarms when offline).

`download_danbooru_tags()` is best-effort: any HTTPError, network failure,
or rate-limit raises a clear exception so callers can decide whether to
retry, fall back, or skip. Tests must NOT call this function — they should
seed the cache directly via the `seed_cache_for_tests` helper.
"""

import csv
import re
from pathlib import Path

import httpx

CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "danbooru_tags.csv"
DANBOORU_API_URL = "https://danbooru.donmai.us/tags.json"

# Danbooru caps `limit` at 1000 per request.
PAGE_SIZE = 1000

# Underscored token: at least one underscore, lowercase letters/digits only.
# This avoids flagging single words like `1girl` (which is a valid booru tag
# but not "underscored") — those are validated only if present in the cache.
# We DO check single-word non-underscored tokens against the cache too, since
# `1girl`, `solo`, `full_body` etc. are all in Danbooru.
_TOKEN = re.compile(r"^[a-z0-9_]+$")


class TagValidatorError(RuntimeError):
    pass


def download_danbooru_tags(
    limit: int = 100_000,
    *,
    cache_path: Path | None = None,
    page_size: int = PAGE_SIZE,
    timeout: float = 30.0,
    user_agent: str = "9LivesK9/0.1 (tag-validator cache build)",
) -> int:
    """Fetch up to `limit` Danbooru tags ordered by post_count desc and
    write them to `cache_path` (default: data/danbooru_tags.csv).

    Returns the number of tags written.

    Raises TagValidatorError if the network call fails or the API returns
    a non-200 status — caller decides fallback. Existing cache is replaced
    only after a successful full pass.
    """
    cache_path = Path(cache_path) if cache_path else CACHE_PATH
    pages = max(1, (limit + page_size - 1) // page_size)
    headers = {"User-Agent": user_agent}
    rows: list[tuple[str, int]] = []
    with httpx.Client(timeout=timeout, headers=headers) as client:
        for page in range(1, pages + 1):
            params = {
                "limit": min(page_size, limit - len(rows)),
                "page": page,
                "search[order]": "count",
            }
            try:
                resp = client.get(DANBOORU_API_URL, params=params)
            except httpx.HTTPError as e:
                raise TagValidatorError(
                    f"network error on page {page}: {e}"
                ) from e
            if resp.status_code != 200:
                raise TagValidatorError(
                    f"Danbooru returned {resp.status_code} on page {page}: "
                    f"{resp.text[:200]}"
                )
            try:
                batch = resp.json()
            except ValueError as e:
                raise TagValidatorError(f"non-JSON response page {page}: {e}") from e
            if not batch:
                break
            for tag in batch:
                name = tag.get("name")
                count = int(tag.get("post_count") or 0)
                if name:
                    rows.append((name, count))
                if len(rows) >= limit:
                    break
            if len(rows) >= limit:
                break

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "post_count"])
        for name, count in rows:
            w.writerow([name, count])
    tmp.replace(cache_path)
    return len(rows)


def load_cache(cache_path: Path | None = None) -> set[str]:
    """Return the set of cached Danbooru tag names. Empty set if cache
    missing or unreadable — never raises.
    """
    cache_path = Path(cache_path) if cache_path else CACHE_PATH
    if not cache_path.exists():
        return set()
    try:
        with open(cache_path, encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            try:
                next(reader)  # header
            except StopIteration:
                return set()
            return {row[0] for row in reader if row and row[0]}
    except (OSError, UnicodeDecodeError, csv.Error):
        return set()


def positive_prompt_tokens(prompt: str) -> list[str]:
    """Comma-tokenize a positive prompt and return tokens stripped of
    whitespace. Empty tokens dropped.
    """
    if not prompt:
        return []
    return [t.strip() for t in prompt.split(",") if t.strip()]


def validate_tokens(
    prompt: str, *, cache_path: Path | None = None
) -> list[str]:
    """Return the list of tokens that look like booru tags
    (lowercase letters/digits/underscores only) but are NOT in the cached
    tag set. If the cache is empty (file missing), returns an empty list —
    we don't generate spurious warnings when validation isn't configured.
    """
    cache = load_cache(cache_path)
    if not cache:
        return []
    unknown: list[str] = []
    for token in positive_prompt_tokens(prompt):
        # We only validate booru-shape tokens (lowercase a-z, 0-9, underscore).
        # Anything containing spaces, capitals, punctuation, or weight syntax
        # like `(x:1.2)` is left alone — those are natural-language clauses or
        # prompt-weight syntax that don't claim to be booru tags.
        if _TOKEN.fullmatch(token) and token not in cache:
            unknown.append(token)
    return unknown


def seed_cache_for_tests(tags: list[str], cache_path: Path) -> None:
    """Test helper: write a tiny synthetic cache so validate_tokens has
    something to compare against without hitting the network.
    """
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "post_count"])
        for t in tags:
            w.writerow([t, 0])
