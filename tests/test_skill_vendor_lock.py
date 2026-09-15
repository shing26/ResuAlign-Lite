"""ADR-0041 决定 11 漂移锁：truetailor skill 仓是 gate.py 与黄金 fixtures 的唯一事实源。

主仓持的是 vendor 副本（`src/resualign/gate.py` + `tests/fixtures/gate/`）。本测试
用 `VENDOR.json` 里记录的哈希断言两侧字节一致：本地偷偷放宽门禁、或绕过 skill 仓
改 fixtures，都会在这里变红，而不只是靠 review 时的人眼。

行尾归一后取哈希（core.autocrlf=true 的机器上 checkout 会变 CRLF），清单里存的是
LF 形态的哈希，因此两侧仓库在任何 checkout 配置下都可比对。
"""

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = ROOT / "tests" / "fixtures" / "gate"
MANIFEST_PATH = VENDOR_DIR / "VENDOR.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_vendored_bytes_match_the_skill_repo(manifest):
    assert manifest["upstream"].startswith("https://github.com/"), manifest
    assert manifest["synced_from"], "no upstream commit recorded"
    for rel, digest in manifest["files"].items():
        path = ROOT / rel
        assert path.exists(), f"vendored file missing: {rel}"
        assert _sha(path) == digest, (
            f"{rel} drifted from the vendored upstream copy "
            f"({manifest['upstream']}@{manifest['synced_from'][:8]}). "
            "Re-sync from the skill repo, or move the rule change there first."
        )


def test_manifest_covers_every_vendored_file(manifest):
    """A new fixture scenario added only here would silently escape the lock."""
    listed = {
        Path(rel).name for rel in manifest["files"] if "fixtures/gate" in rel.replace("\\", "/")
    }
    on_disk = {p.name for p in VENDOR_DIR.iterdir() if p.name != MANIFEST_PATH.name}
    assert listed == on_disk, on_disk ^ listed


def test_gate_source_is_the_vendored_copy(manifest):
    """The app's live gate module IS the skill repo's file, byte for byte.

    tailor.py keeps its own copy of the content check for historical reasons;
    test_gate.py::TestDriftLockParity locks their verdicts together. This test
    locks the file itself, so gate.py cannot be softened here and left strict
    upstream.
    """
    digest = manifest["files"]["src/resualign/gate.py"]
    assert _sha(ROOT / "src/resualign/gate.py") == digest
