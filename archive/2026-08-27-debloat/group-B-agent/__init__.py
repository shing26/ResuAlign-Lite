"""Agent-native backend for ResuAlign (Sprint 6).

This package adds the three agent-facing surfaces on top of the FastAPI
application:

- ``mcp_server``: an MCP (Model Context Protocol) server exposing the job
  library pipeline as 4 tools (fetch+evaluate, auto-align, blockers).
- ``hitl``: human-in-the-loop webhook fan-out (``RESUALIGN_WEBHOOK_URL``)
  with structured-log fallback, used by the fetcher pipeline and MCP tools.
- ``headless``: a daemon loop that polls blockers and auto-queues alignment
  runs without a web frontend.
- ``orchestrator``: the JD intake agent loop (ADR-0029 Phase A) that drives
  the MCP tools with a bounded decision round per blocker.
- ``policy_llm``: optional LLM-backed keep/resolve policy used by the
  orchestrator and the headless daemon.

Importing this package is side-effect free: ``hitl`` only depends on the
stdlib + httpx, while ``mcp_server``/``headless`` pull in the FastMCP SDK
and the FastAPI layer. Keep heavy imports out of this ``__init__`` so the
API layer can import ``resualign.agent.hitl`` (from the fetcher service)
without booting the MCP server.
"""
