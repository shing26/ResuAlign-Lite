"""Layer-ratchet guards for ``resualign.tools.modgraph``.

The tool existed as an unused scratch script with two silent defects: the
``api/`` prefix shadowed ``api/services/`` (so the 服务 layer could never be
returned), and the violation check only fired for inner source layers (so
service -> API was invisible). These tests pin both fixes and the ratchet
semantics that keep them from regressing.
"""

from __future__ import annotations

import pytest

from resualign.tools import modgraph


def test_layer_of_prefers_the_longest_prefix():
    assert modgraph.layer_of("api/services/jobs.py") == "服务"
    assert modgraph.layer_of("api/routers/jobs.py") == "API"
    assert modgraph.layer_of("api/__init__.py") == "API"


def test_layer_of_does_not_match_longer_siblings():
    # R7 把 engine 从模块改成包；层匹配走目录前缀，包内文件归引擎层。
    assert modgraph.layer_of("engine/__init__.py") == "引擎"
    assert modgraph.layer_of("engine/llm.py") == "引擎"
    assert modgraph.layer_of("engine_utils.py") == "其他"
    assert modgraph.layer_of("jobs.py") == "存储"
    assert modgraph.layer_of("jobs_extra.py") == "其他"


def test_service_to_api_is_a_violation():
    all_mods = {
        "resualign.api.services.thing": modgraph.PKG / "api/services/thing.py",
        "resualign.api": modgraph.PKG / "api/__init__.py",
    }
    edges = {"resualign.api.services.thing": {"resualign.api"}}
    assert modgraph.layering_violations(edges, all_mods) == [
        (
            "resualign.api.services.thing",
            "服务",
            "resualign.api",
            "API",
        )
    ]


def test_service_to_service_stays_allowed():
    all_mods = {
        "resualign.api.services.a": modgraph.PKG / "api/services/a.py",
        "resualign.api.services.b": modgraph.PKG / "api/services/b.py",
    }
    edges = {"resualign.api.services.a": {"resualign.api.services.b"}}
    assert modgraph.layering_violations(edges, all_mods) == []


def test_inner_layer_reaching_service_is_a_violation():
    all_mods = {
        "resualign.engine": modgraph.PKG / "engine/__init__.py",
        "resualign.api.services.thing": modgraph.PKG / "api/services/thing.py",
    }
    edges = {"resualign.engine": {"resualign.api.services.thing"}}
    assert modgraph.layering_violations(edges, all_mods) == [
        ("resualign.engine", "引擎", "resualign.api.services.thing", "服务")
    ]


@pytest.fixture
def clean_baseline():
    return {"layering_violations": [], "cycles": [], "api_module_refs": {}}


def test_ratchet_flags_new_violation(clean_baseline):
    data = {
        "violations": ["a [服务] -> b [API]"],
        "cycles": [],
        "api_module_refs": {},
    }
    assert modgraph.check_against_baseline(data, clean_baseline) == 1


def test_ratchet_allows_shrinking(clean_baseline):
    baseline = dict(clean_baseline, layering_violations=["old [服务] -> b [API]"])
    data = {"violations": [], "cycles": [], "api_module_refs": {}}
    assert modgraph.check_against_baseline(data, baseline) == 0


def test_ratchet_flags_new_cycle(clean_baseline):
    data = {"violations": [], "cycles": ["a | b"], "api_module_refs": {}}
    assert modgraph.check_against_baseline(data, clean_baseline) == 1


def test_ratchet_flags_reference_count_growth(clean_baseline):
    baseline = dict(clean_baseline, api_module_refs={"jobs.py::_registry": 2})
    data = {
        "violations": [],
        "cycles": [],
        "api_module_refs": {"jobs.py::_registry": 3},
    }
    assert modgraph.check_against_baseline(data, baseline) == 1


def test_api_module_refs_counts_sites_and_ignores_comments(tmp_path, monkeypatch):
    monkeypatch.setattr(modgraph, "PKG", tmp_path)
    source = tmp_path / "mod.py"
    source.write_text(
        "api_module._registry.fail(1)\n"
        "x = api_module._registry\n"
        "# api_module._commented_out\n",
        encoding="utf-8",
    )
    assert modgraph.api_module_refs([source]) == {"mod.py::_registry": 2}


def test_checked_in_baseline_matches_the_tree():
    """CI runs the same comparison; a stale baseline must fail here first."""
    files = sorted(
        p for p in modgraph.PKG.rglob("*.py") if "__pycache__" not in p.parts
    )
    data = modgraph.collect(files)
    baseline = modgraph.load_baseline(modgraph.BASELINE_PATH)
    assert modgraph.check_against_baseline(data, baseline) == 0
