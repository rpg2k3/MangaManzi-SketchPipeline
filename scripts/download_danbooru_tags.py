"""Download top-100k Danbooru tags by post_count for the booru-tag
validator (Phase 3). Best-effort — network failures are reported but
non-fatal to the running app.

Usage:
    .venv/bin/python scripts/download_danbooru_tags.py [--limit N]

By default writes data/danbooru_tags.csv with two columns: name,post_count.
"""

import argparse
import sys
from pathlib import Path

# Make the repo root importable regardless of CWD.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.pixai.tag_validator import (  # noqa: E402
    CACHE_PATH,
    TagValidatorError,
    download_danbooru_tags,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100_000)
    parser.add_argument("--out", type=Path, default=CACHE_PATH)
    args = parser.parse_args()

    print(f"Downloading top-{args.limit} Danbooru tags to {args.out} ...", flush=True)
    try:
        n = download_danbooru_tags(limit=args.limit, cache_path=args.out)
    except TagValidatorError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 2
    print(f"Wrote {n} tags.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
