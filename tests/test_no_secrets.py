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
# Matched against the SECRET TEXT ITSELF, not the whole line (verifier PR #18 finding 7:
# a line-level match let "latest"/"attestation" comments hide a real token).
FAKE_MARKERS = ("fake", "not-real", "not_real", "test", "example", "dummy", "throwaway", "decoy")
# Credential shapes this project actually uses.
PATTERNS.update(
    {
        "url with password": re.compile(r"\b[a-z][a-z0-9+]*://[^\s:/@]+:([^\s@/]+)@"),
        "secret assignment": re.compile(
            r"\b(?:VTP_PASSWORD|VTP_TOKEN|WEBHOOK_SHARED_SECRET|API_KEYS|DATABASE_URL)"
            r"[ \t]*=[ \t]*[\"']?([^\s\"'#]{8,})"
        ),
    }
)


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
                secret = match.group(match.lastindex) if match.lastindex else match.group(0)
                if any(marker in secret.lower() for marker in FAKE_MARKERS):
                    continue
                if name == "secret assignment" and secret.startswith(("sqlite:", "$")):
                    continue
                if secret.startswith("<") and secret.endswith(">"):
                    continue  # documentation placeholder such as <pass>
                findings.append(f"{path.relative_to(ROOT)}: {name}")
    assert findings == []


def test_no_env_or_database_files_tracked():
    names = [p.name for p in tracked_files()]
    assert ".env" not in names
    assert not [n for n in names if n.endswith((".db", ".sqlite", ".pem", ".key"))]


def test_tests_never_use_the_default_database_url():
    from app.core.config import settings

    assert "vip_shipping.db" not in settings.database_url
    assert settings.database_url.startswith("sqlite:///")


def test_tripwire_catches_what_it_should():
    """The patterns and allow-list themselves (samples built at runtime, not stored)."""
    jwt = "eyJ" + "a" * 20 + ".eyJ" + "b" * 20 + "." + "c" * 12
    gh = "ghp_" + "Z" * 36
    samples = {
        f"token = '{jwt}'  # latest token": True,
        f"x = '{gh}'  # attestation": True,
        "DATABASE" + "_URL=postgresql://svc:" + "Pa55" + "word9@db:5432/x": True,
        "WEBHOOK" + "_SHARED_SECRET=" + "q" * 20: True,
        "VTP" + "_PASSWORD=\nVTP" + "_TOKEN=": False,  # empty values must not span lines
        "postgresql+psycopg://ci:ci-only-throwaway@localhost/x": False,
        "DATABASE_URL=sqlite:///./vip_shipping.db": False,
        "postgresql+psycopg://<user>:<pass>@<host>:5432/db": False,  # doc placeholder
        "WEBHOOK_SHARED_SECRET=": False,
    }
    for line, expected in samples.items():
        hit = False
        for pattern in PATTERNS.values():
            for m in pattern.finditer(line):
                secret = m.group(m.lastindex) if m.lastindex else m.group(0)
                if any(k in secret.lower() for k in FAKE_MARKERS):
                    continue
                if secret.startswith(("sqlite:", "$")):
                    continue
                if secret.startswith("<") and secret.endswith(">"):
                    continue
                hit = True
        assert hit is expected, line
