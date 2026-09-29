"""Generate an API key and its API_KEYS entry.

    python -m app.tools.api_key <key_id>

Prints the raw key ONCE (give it to the caller through a secret channel) and the
``<key_id>:<sha256>`` entry to put in the API_KEYS secret. Nothing is written to disk.
"""

import secrets
import sys

from app.api.auth import hash_key


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m app.tools.api_key <key_id>", file=sys.stderr)
        return 2
    key = secrets.token_urlsafe(32)
    print(f"raw key (show once, do not store in the repo): {key}")
    print(f"API_KEYS entry: {argv[0]}:{hash_key(key)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
