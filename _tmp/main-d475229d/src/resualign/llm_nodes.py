"""Tenant-scoped LLM provider node store (multi-node configuration).

Each tenant can register several LLM nodes (provider / base_url / api_key /
model combinations) and keep exactly one active at a time. ``build_config()``
reads the active node on every call via the registered stored-provider
callback, so activating a different node hot-reloads the pipeline config
without a restart. When a tenant has no nodes, the legacy single-node ``llm``
settings field (user_settings) remains the fallback.

The table is a separate domain from ``user_settings`` and gets its own
store-scoped migration journal (``schema_migrations.store = LLMNodeStore``),
which ``store_base`` already keys by class name.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from .store_base import UserStoreError, _SqliteStore

_LLM_NODES_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_nodes (
    node_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    provider TEXT NOT NULL,
    base_url TEXT,
    api_key TEXT,
    model TEXT,
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_nodes_tenant
    ON llm_nodes(tenant_id);
-- At most one active node per tenant, enforced at the DB level.
CREATE UNIQUE INDEX IF NOT EXISTS idx_llm_nodes_one_active
    ON llm_nodes(tenant_id) WHERE is_active = 1;
"""

_NODE_FIELDS = (
    "node_id",
    "tenant_id",
    "name",
    "provider",
    "base_url",
    "api_key",
    "model",
    "is_active",
    "created_at",
    "updated_at",
)

_EDITABLE_FIELDS = ("name", "provider", "base_url", "api_key", "model", "is_active")

_ALLOWED_PROVIDERS = ("deepseek", "openrouter", "ollama")

_LLM_ROLES = ("diagnose", "profiler", "gap_analyzer", "editor", "evaluator")
_LLM_ROLE_ASSIGNMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_role_assignments (
    tenant_id TEXT NOT NULL,
    role TEXT NOT NULL,
    node_id TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (tenant_id, role)
);
"""


class LLMNodeStore(_SqliteStore):
    """Store and validate per-tenant LLM provider nodes."""

    SCHEMA_SQL = _LLM_NODES_SCHEMA

    MIGRATIONS = (
        (
            1,
            "CREATE TABLE IF NOT EXISTS llm_nodes ("
            "node_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, "
            "name TEXT NOT NULL, provider TEXT NOT NULL, base_url TEXT, "
            "api_key TEXT, model TEXT, is_active INTEGER NOT NULL DEFAULT 0, "
            "created_at REAL NOT NULL, updated_at REAL NOT NULL); "
            "CREATE INDEX IF NOT EXISTS idx_llm_nodes_tenant "
            "ON llm_nodes(tenant_id); "
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_llm_nodes_one_active "
            "ON llm_nodes(tenant_id) WHERE is_active = 1;",
        ),
        (
            2,
            "CREATE TABLE IF NOT EXISTS llm_role_assignments ("
            "tenant_id TEXT NOT NULL, role TEXT NOT NULL, "
            "node_id TEXT NOT NULL, updated_at REAL NOT NULL, "
            "PRIMARY KEY (tenant_id, role));",
        ),
    )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Role bindings
    # ------------------------------------------------------------------

    def set_role_binding(
        self, tenant_id: str, role: str, node_id: str
    ) -> bool:
        if role not in _LLM_ROLES:
            raise UserStoreError(
                f"role must be one of {_LLM_ROLES}, got {role!r}"
            )
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                node = conn.execute(
                    "SELECT 1 FROM llm_nodes "
                    "WHERE tenant_id = ? AND node_id = ?",
                    (tenant_id, node_id),
                ).fetchone()
                if node is None:
                    return False
                conn.execute(
                    "INSERT INTO llm_role_assignments "
                    "(tenant_id, role, node_id, updated_at) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(tenant_id, role) DO UPDATE SET "
                    "node_id = excluded.node_id, updated_at = excluded.updated_at",
                    (tenant_id, role, node_id, time.time()),
                )
        return True

    def get_role_binding(self, tenant_id: str, role: str) -> str | None:
        if role not in _LLM_ROLES:
            return None
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT node_id FROM llm_role_assignments "
                    "WHERE tenant_id = ? AND role = ?",
                    (tenant_id, role),
                ).fetchone()
        return row["node_id"] if row is not None else None

    def get_role_bindings(self, tenant_id: str) -> dict[str, str]:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT role, node_id FROM llm_role_assignments "
                    "WHERE tenant_id = ?",
                    (tenant_id,),
                ).fetchall()
        return {row["role"]: row["node_id"] for row in rows}

    def delete_role_binding(self, tenant_id: str, role: str) -> bool:
        if role not in _LLM_ROLES:
            return False
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                cursor = conn.execute(
                    "DELETE FROM llm_role_assignments "
                    "WHERE tenant_id = ? AND role = ?",
                    (tenant_id, role),
                )
        return cursor.rowcount > 0

    def resolve_node_for_role(self, tenant_id: str, role: str) -> dict[str, Any] | None:
        bound_id = self.get_role_binding(tenant_id, role)
        if bound_id is not None:
            node = self.get_node(tenant_id, bound_id)
            if node is not None:
                return node
            self.delete_role_binding(tenant_id, role)
        return self.get_active_node(tenant_id)

    def clear_role_bindings(self, tenant_id: str) -> None:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM llm_role_assignments WHERE tenant_id = ?",
                    (tenant_id,),
                )

    @staticmethod
    def _is_local_node(node: dict[str, Any] | None) -> bool:
        if node is None:
            return False
        if node.get("provider") == "ollama":
            return True
        base_url = (node.get("base_url") or "").lower()
        return "localhost" in base_url or "127.0.0.1" in base_url

    @staticmethod
    def list_roles() -> tuple[str, ...]:
        return _LLM_ROLES

    def list_nodes(self, tenant_id: str) -> list[dict[str, Any]]:
        """Return the tenant's nodes in creation order."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                rows = conn.execute(
                    f"SELECT {','.join(_NODE_FIELDS)} FROM llm_nodes "
                    "WHERE tenant_id = ? ORDER BY created_at ASC, node_id ASC",
                    (tenant_id,),
                ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_node(
        self, tenant_id: str, node_id: str
    ) -> dict[str, Any] | None:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    f"SELECT {','.join(_NODE_FIELDS)} FROM llm_nodes "
                    "WHERE tenant_id = ? AND node_id = ?",
                    (tenant_id, node_id),
                ).fetchone()
        return self._row_to_dict(row) if row is not None else None

    def get_active_node(self, tenant_id: str) -> dict[str, Any] | None:
        """Return the tenant's single active node, or None."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    f"SELECT {','.join(_NODE_FIELDS)} FROM llm_nodes "
                    "WHERE tenant_id = ? AND is_active = 1 LIMIT 1",
                    (tenant_id,),
                ).fetchone()
        return self._row_to_dict(row) if row is not None else None

    def count_nodes(self, tenant_id: str) -> int:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM llm_nodes WHERE tenant_id = ?",
                    (tenant_id,),
                ).fetchone()
        return int(row["c"])

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def create_node(
        self,
        tenant_id: str,
        *,
        name: str,
        provider: str,
        model: str,
        base_url: str | None = None,
        api_key: str | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any]:
        """Insert a node and return it.

        The first node of a tenant becomes active automatically; an explicit
        ``is_active=True`` activates the new node and deactivates every other
        node of the tenant (one active node per tenant).
        """
        self._validate_node(
            name=name,
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            is_active=is_active,
        )
        node_id = uuid.uuid4().hex
        now = time.time()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                existing = conn.execute(
                    "SELECT COUNT(*) AS c FROM llm_nodes WHERE tenant_id = ?",
                    (tenant_id,),
                ).fetchone()["c"]
                activate = existing == 0 or is_active is True
                if activate:
                    conn.execute(
                        "UPDATE llm_nodes SET is_active = 0 "
                        "WHERE tenant_id = ? AND is_active = 1",
                        (tenant_id,),
                    )
                conn.execute(
                    "INSERT INTO llm_nodes (node_id, tenant_id, name, "
                    "provider, base_url, api_key, model, is_active, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, "
                    "?, ?, ?)",
                    (
                        node_id,
                        tenant_id,
                        name,
                        provider,
                        base_url,
                        api_key,
                        model,
                        int(activate),
                        now,
                        now,
                    ),
                )
        node = self.get_node(tenant_id, node_id)
        assert node is not None
        return node

    def update_node(
        self, tenant_id: str, node_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Partially update a node; return None when the node is missing.

        ``is_active=True`` switches the tenant's active node (all others are
        deactivated first); ``is_active=False`` simply marks the node
        inactive. Omitted keys keep their stored value.
        """
        node = self.get_node(tenant_id, node_id)
        if node is None:
            return None
        merged = {key: updates.get(key, node[key]) for key in _EDITABLE_FIELDS}
        self._validate_node(
            name=merged["name"],
            provider=merged["provider"],
            model=merged["model"],
            base_url=merged["base_url"],
            api_key=merged["api_key"],
            is_active=merged["is_active"],
        )
        now = time.time()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                if merged["is_active"] is True:
                    conn.execute(
                        "UPDATE llm_nodes SET is_active = 0 "
                        "WHERE tenant_id = ? AND is_active = 1",
                        (tenant_id,),
                    )
                conn.execute(
                    "UPDATE llm_nodes SET name = ?, provider = ?, "
                    "base_url = ?, api_key = ?, model = ?, is_active = ?, "
                    "updated_at = ? WHERE tenant_id = ? AND node_id = ?",
                    (
                        merged["name"],
                        merged["provider"],
                        merged["base_url"],
                        merged["api_key"],
                        merged["model"],
                        int(bool(merged["is_active"])),
                        now,
                        tenant_id,
                        node_id,
                    ),
                )
        return self.get_node(tenant_id, node_id)

    def delete_node(self, tenant_id: str, node_id: str) -> bool:
        """Delete a node; return False when it does not exist.

        Deleting the active node promotes the oldest remaining node to
        active (creation order), keeping the tenant with exactly one active
        node whenever any node remains.
        """
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT is_active FROM llm_nodes "
                    "WHERE tenant_id = ? AND node_id = ?",
                    (tenant_id, node_id),
                ).fetchone()
                if row is None:
                    return False
                was_active = bool(row["is_active"])
                conn.execute(
                    "DELETE FROM llm_nodes WHERE tenant_id = ? AND node_id = ?",
                    (tenant_id, node_id),
                )
                if was_active:
                    next_row = conn.execute(
                        "SELECT node_id FROM llm_nodes WHERE tenant_id = ? "
                        "ORDER BY created_at ASC, node_id ASC LIMIT 1",
                        (tenant_id,),
                    ).fetchone()
                    if next_row is not None:
                        conn.execute(
                            "UPDATE llm_nodes SET is_active = 1, "
                            "updated_at = ? WHERE tenant_id = ? AND node_id = ?",
                            (time.time(), tenant_id, next_row["node_id"]),
                        )
                return True

    def activate_node(
        self, tenant_id: str, node_id: str
    ) -> dict[str, Any] | None:
        """Activate one node and deactivate every other node of the tenant."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT node_id FROM llm_nodes "
                    "WHERE tenant_id = ? AND node_id = ?",
                    (tenant_id, node_id),
                ).fetchone()
                if row is None:
                    return None
                now = time.time()
                conn.execute(
                    "UPDATE llm_nodes SET is_active = 0, updated_at = ? "
                    "WHERE tenant_id = ? AND is_active = 1",
                    (now, tenant_id),
                )
                conn.execute(
                    "UPDATE llm_nodes SET is_active = 1, updated_at = ? "
                    "WHERE tenant_id = ? AND node_id = ?",
                    (now, tenant_id, node_id),
                )
        return self.get_node(tenant_id, node_id)

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_node(
        *,
        name: str | None,
        provider: str | None,
        model: str | None,
        base_url: str | None = None,
        api_key: str | None = None,
        is_active: bool | None = None,
    ) -> None:
        if not str(name or "").strip():
            raise UserStoreError("name must be a non-empty string")
        if provider not in _ALLOWED_PROVIDERS:
            raise UserStoreError(
                "provider must be one of deepseek, openrouter, ollama"
            )
        if not str(model or "").strip():
            raise UserStoreError("model must be a non-empty string")
        for key, value in (("base_url", base_url), ("api_key", api_key)):
            if value is not None and not isinstance(value, str):
                raise UserStoreError(f"{key} must be a string or null")
        if is_active is not None and not isinstance(is_active, bool):
            raise UserStoreError("is_active must be a boolean")

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        return {
            "node_id": row["node_id"],
            "tenant_id": row["tenant_id"],
            "name": row["name"],
            "provider": row["provider"],
            "base_url": row["base_url"],
            "api_key": row["api_key"],
            "model": row["model"],
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
