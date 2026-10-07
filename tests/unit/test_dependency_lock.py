"""The hash-pinned locks must stay honest about what they lock.

`requirements.txt` declares what we depend on; `requirements.lock` is what actually gets
installed, every transitive package pinned with its hashes. The danger is drift: somebody
bumps a version in requirements.txt, nobody regenerates the lock, and from then on the
declared file and the installed set are two different things — while every build stays
green, because the lock still resolves. These checks are cheap and they fail loudly.

Regenerate both locks with:

    uv pip compile requirements.txt     --universal --generate-hashes \\
        --python-version 3.11 -o requirements.lock
    uv pip compile requirements-dev.txt --universal --generate-hashes \\
        --python-version 3.11 -o requirements-dev.lock
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PINNED = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*==\s*([^\s;\\]+)")
LOCKS = {"requirements.txt": "requirements.lock", "requirements-dev.txt": "requirements-dev.lock"}


def normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def declared(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        match = PINNED.match(line)
        assert match, f"{path.name}: '{line}' is not pinned with == , so the lock cannot be trusted"
        out[normalise(match.group(1))] = match.group(2)
    return out


def locked(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith((" ", "#")) or not line.strip():
            continue
        match = PINNED.match(line.strip())
        if match:
            out[normalise(match.group(1))] = match.group(2)
    return out


@pytest.mark.parametrize("source,lock", LOCKS.items())
def test_every_declared_dependency_is_in_the_lock_at_the_same_version(source, lock):
    want = declared(ROOT / source)
    have = locked(ROOT / lock)
    assert want, f"{source} parsed empty — this check would pass vacuously"
    missing = sorted(set(want) - set(have))
    assert not missing, f"{lock} does not contain {missing}; regenerate it (see this file)"
    drifted = {k: (v, have[k]) for k, v in want.items() if have[k] != v}
    assert not drifted, f"{source} and {lock} disagree on versions: {drifted}"


@pytest.mark.parametrize("lock", sorted(set(LOCKS.values())))
def test_every_locked_package_carries_hashes(lock):
    """A lock entry without hashes installs whatever the index serves that day."""
    text = (ROOT / lock).read_text(encoding="utf-8")
    entries = [b for b in re.split(r"\n(?=[A-Za-z0-9])", text) if PINNED.match(b.strip())]
    assert len(entries) > len(declared(ROOT / "requirements.txt")), (
        f"{lock} should pin transitive packages too, not only the declared ones"
    )
    unhashed = [b.split("\n", 1)[0] for b in entries if "--hash=sha256:" not in b]
    assert not unhashed, f"{lock}: no hashes for {unhashed}"


def test_the_image_installs_from_the_lock_not_the_declared_file():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "--require-hashes -r requirements.lock" in dockerfile
    assert not re.search(r"pip install[^\n]*-r requirements\.txt", dockerfile)


def test_the_base_image_is_pinned_by_digest():
    """A tag is a moving target: two builds of one commit could differ."""
    from_lines = [
        line
        for line in (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
        if line.startswith("FROM ")
    ]
    assert from_lines
    for line in from_lines:
        assert re.search(r"@sha256:[0-9a-f]{64}", line), f"not pinned by digest: {line}"


def test_ci_installs_from_the_locks():
    for workflow in ("ci", "staging"):
        text = (ROOT / ".github" / "workflows" / f"{workflow}.yml").read_text(encoding="utf-8")
        assert not re.search(r"pip install -r requirements(-dev)?\.txt", text), (
            f"{workflow}.yml still installs from a file without hashes"
        )
