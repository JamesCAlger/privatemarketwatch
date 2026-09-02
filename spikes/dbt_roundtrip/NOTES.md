# Spike ergonomics log (kill-criterion-3 evidence)

Append one line at start/end of each task: [YYYY-MM-DD HH:MM] Task N start|end - note.
Record every framework workaround (dbt quirk, config fight, docs gap) as its own line.

[2026-09-02 20:35] Task 1 workaround: dbt-duckdb install would upgrade protobuf 5.29.5->6.33.6 (major breaking version). Installed dbt-duckdb (1.11.0) + dbt-core (1.12.3) in isolated .venv/ instead of shared conda env to avoid conflict with pytest suite. dbt --version confirmed both plugins working.
