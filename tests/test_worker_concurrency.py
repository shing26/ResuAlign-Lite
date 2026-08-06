"""Worker concurrency configuration: clamp range, env override, semaphore.

Analysis jobs are LLM-bound; ``RESUALIGN_WORKER_CONCURRENCY`` (1..4) widens
the in-process worker semaphore so batch-alignment jobs run in parallel
instead of serial. Values outside 1..4 are clamped, never raised.
"""

import os
import subprocess
import sys
from pathlib import Path

from resualign.api.state import _clamp_worker_concurrency


def test_clamp_lower_bound():
    assert _clamp_worker_concurrency(0) == 1
    assert _clamp_worker_concurrency(-5) == 1


def test_clamp_upper_bound():
    assert _clamp_worker_concurrency(4) == 4
    assert _clamp_worker_concurrency(99) == 4


def test_clamp_in_range_passthrough():
    assert _clamp_worker_concurrency(1) == 1
    assert _clamp_worker_concurrency(2) == 2
    assert _clamp_worker_concurrency(3) == 3


def test_clamp_invalid_values_default_to_one():
    assert _clamp_worker_concurrency(None) == 1
    assert _clamp_worker_concurrency("abc") == 1
    assert _clamp_worker_concurrency("") == 1


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


def test_env_out_of_range_is_clamped():
    assert _import_concurrency("99") == 4
    assert _import_concurrency("0") == 1
    assert _import_concurrency("abc") == 1
