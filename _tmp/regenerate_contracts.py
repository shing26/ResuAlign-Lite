#!/usr/bin/env python
"""Regenerate contracts/openapi-current.json and contracts/incremental/manifest.json.

Run from repo root: PYTHONPATH=src python _tmp/regenerate_contracts.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

from resualign.api import app  # noqa: E402

CONTRACTS_DIR = Path("contracts")
OPENAPI_GOLDEN = CONTRACTS_DIR / "openapi-v1.json"
OPENAPI_CURRENT = CONTRACTS_DIR / "openapi-current.json"
INCREMENTAL_MANIFEST = CONTRACTS_DIR / "incremental" / "manifest.json"

current = app.openapi()
golden = json.loads(OPENAPI_GOLDEN.read_text(encoding="utf-8"))

new_paths = sorted(set(current["paths"]) - set(golden["paths"]))
new_schemas = sorted(
    set(current["components"]["schemas"]) - set(golden["components"]["schemas"])
)
removed_paths = sorted(set(golden["paths"]) - set(current["paths"]))

removed_props = {}
for name, schema in golden["components"]["schemas"].items():
    if name not in current["components"]["schemas"]:
        continue
    golden_props = set((schema.get("properties") or {}).keys())
    current_props = set(
        (current["components"]["schemas"][name].get("properties") or {}).keys()
    )
    missing = sorted(golden_props - current_props)
    if missing:
        removed_props[name] = missing

manifest = json.loads(INCREMENTAL_MANIFEST.read_text(encoding="utf-8"))
manifest["paths"] = new_paths
manifest["schemas"] = new_schemas
manifest["removed_paths"] = removed_paths
manifest["removed_schema_properties"] = removed_props
manifest["operations"] = []

OPENAPI_CURRENT.write_text(
    json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
INCREMENTAL_MANIFEST.write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print("new_paths:", new_paths)
print("new_schemas:", new_schemas)
print("removed_paths:", removed_paths)
print("removed_props:", removed_props)
print("OK")