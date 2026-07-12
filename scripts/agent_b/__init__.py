"""Agent B (Adjudicator) -- deterministic Layer-1 spine for the Codex worker fleet.

Mirrors ``scripts/agent_a`` but for verdict adjudication: discover a sample of the
flagged population, build bounded bundles, dispatch one blinded worker per bundle,
collect + validate the verdict leaves, and route. No LLM here; the worker step is the
sandboxed Codex fleet (see scripts/dispatch_agent_b_workers.ps1).
"""
