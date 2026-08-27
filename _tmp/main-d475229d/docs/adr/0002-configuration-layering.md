 # ADR-002: Configuration layering (CLI > .env > env)

 **Status**: Proposed
 **Date**: 2026-07-31

 ## Context

 The tool currently reads all configuration from environment variables (`LLM_PROVIDER`, `DEEPSEEK_API_KEY`, etc.). This means the user must re-export vars in every terminal session or persist them globally, both of which are inconvenient for a tool used across different projects/APIs.

 ## Decision

 Layer configuration in three levels, where higher overrides lower:

 1. **CLI flags** (`--api-key`, `--model`, `--provider`) — highest priority, per-run override
 2. **`.env` file** — loaded from the working directory via `python-dotenv`; shared with the team via `.env.example`
 3. **Environment variables** — lowest priority, fallback for CI or global setup

 ## Consequences

 - Users can set their key once in `.env` and forget about it.
 - `.env.example` serves as documentation for required/optional config.
 - CLI flags stay optional; most users only need `.env`.
 - Adds `python-dotenv` as a dependency (~small, pure-Python).
