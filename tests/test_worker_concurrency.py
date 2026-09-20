"""Worker concurrency configuration: range validation, env override, semaphore.

Analysis jobs are LLM-bound; ``RESUALIGN_WORKER_CONCURRENCY`` (1..4) widens
the in-process worker semaphore so batch-alignment jobs run in parallel
instead of serial. Values outside 1..4 fail fast with the variable name.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from resualign.api.state import _clamp_worker_concurrency


def test_rejects_below_lower_bound():
    with pytest.raises(ValueError, match="RESUALIGN_WORKER_CONCURRENCY"):
        _clamp_worker_concurrency(0)
    with pytest.raises(ValueError, match="1..4"):
        _clamp_worker_concurrency(-5)


def test_accepts_upper_bound_and_rejects_above():
    assert _clamp_worker_concurrency(4) == 4
    with pytest.raises(ValueError, match="RESUALIGN_WORKER_CONCURRENCY"):
        _clamp_worker_concurrency(99)


def test_in_range_passthrough():
    assert _clamp_worker_concurrency(1) == 1
    assert _clamp_worker_concurrency(2) == 2
    assert _clamp_worker_concurrency(3) == 3


def test_invalid_values_fail_fast():
    for bad in (None, "abc", ""):
        with pytest.raises(ValueError, match="RESUALIGN_WORKER_CONCURRENCY"):
            _clamp_worker_concurrency(bad)


def _import_concurrency(env_value: str | None) -> int:
    env = os.environ.copy()
    if env_value is None:
        env.pop("RESUALIGN_WORKER_CONCURRENCY", None)
    else:
        env["RESUALIGN_WORKER_CONCURRENCY"] = env_value
    code = (
        "import sys; sys.path.insert(0, 'src'); "
        "import resualign.api as api_module; "
        "print(api_module._WORKER_CONCURRENCY)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return int(proc.stdout.strip())


def test_default_concurrency_is_one():
    assert _import_concurrency(None) == 1


def test_env_override_widens_semaphore():
    assert _import_concurrency("3") == 3


def _import_concurrency_failure(env_value: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["RESUALIGN_WORKER_CONCURRENCY"] = env_value
    code = (
        "import sys; sys.path.insert(0, 'src'); "
        "import resualign.api as api_module"
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=60,
    )


@pytest.mark.parametrize("bad", ["99", "0", "abc"])
def test_env_out_of_range_fails_startup(bad):
    proc = _import_concurrency_failure(bad)
    assert proc.returncode != 0
    assert "RESUALIGN_WORKER_CONCURRENCY" in proc.stderr
