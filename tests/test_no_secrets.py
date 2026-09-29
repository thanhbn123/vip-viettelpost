"""G12: tracked files contain no credential-shaped strings (a CI tripwire, not a full scanner).

Scope: files tracked by git at the current commit. History was scanned separately
(docs/SECURITY.md, "Security posture"). Test fixtures use obviously fake values, which
are allow-listed by the markers below.
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "github token": re.compile(
        r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"
    ),
    "aws access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "openai-style key": re.compile(r"\bsk-[A-Za-z0-9]{32,}"),
    "slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{15,}\.eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}"),
}
FAKE_MARKERS = ("fake", "not-real", "not_real", "test", "example", "dummy")


def tracked_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return [ROOT / line for line in out.splitlines() if line]


def test_no_credential_shaped_strings_in_tracked_files():
    findings = []
    for path in tracked_files():
        if path.suffix in {".png", ".jpg", ".ico", ".zip"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                line = text[text.rfind("\n", 0, match.start()) + 1 : text.find("\n", match.end())]
                if any(marker in line.lower() for marker in FAKE_MARKERS):
                    continue
                findings.append(f"{path.relative_to(ROOT)}: {name}")
    assert findings == []


def test_no_env_or_database_files_tracked():
    names = [p.name for p in tracked_files()]
    assert ".env" not in names
    assert not [n for n in names if n.endswith((".db", ".sqlite", ".pem", ".key"))]
