# Data Engineering Practices for the Fund Reconciliation Project

## Context

This document captures data engineering practices that apply specifically to the fund reconciliation project: a research-stage system unifying five data sources into two datasets (fund-level and investee-level) covering Q4 2022 through Q4 2026, with an agentic data quality system planned on top of the existing transformation logic. The quarterly pipeline does not yet exist; the immediate goal is to get the current dataset right and lay a foundation that the agentic system can reason about and that the future quarterly pipeline can extend.

The practices below are listed in rough order of leverage — how much each one improves the surrounding system, particularly the agentic layer, when it's in place. Not all apply equally at the current research stage; some are more relevant once the quarterly pipeline emerges. A "When to invest" note appears at the end of each section.

---

## 1. Version Control and Reviewable Artifacts

Every change to a transformation, rule, or schema goes through version control with code review. dbt makes this natural; resist any pressure to make rules editable outside this flow ("the analyst should be able to tweak the threshold without bothering engineering"). The moment rules can change outside Git, the agentic system's audit trail is broken — when a rule misfires in Q3, you need to be able to reconstruct the exact rule definition in force at Q2, and that requires the rule history to live in a versioned artifact that no human can mutate without leaving a trace.

This extends to agent outputs. Proposed rules go into pull requests, not direct deploys. The human approval gate becomes a PR review with structured fields the agent populates: which FAILs prompted this proposal, what the proposer claimed the rule enforces, what the sandbox results were, what holdout performance was. Rejected proposals are kept as closed PRs because they are as informative as accepted ones.

**When to invest:** Now. Costs nothing and unlocks the rest.

---

## 2. Layered Transformations: The Medallion Architecture

The bronze/silver/gold model — called the medallion architecture — is the most widely adopted convention for warehouse-based analytical work. For this project it is the right fit, and adopting it deliberately rather than by accident gives the rest of the architecture in this document a sensible home.

### Why this pattern fits the project

The conditions under which medallion is genuinely the right shape, rather than just the popular shape, are all met here: multiple sources (five) requiring conformance into fewer outputs (two); audit-sensitive financial data where reproducibility from raw inputs matters; downstream consumers (the agentic system, business rules, future reporting) that want clean, well-typed tables; and a tabular batch (quarterly) workload, which is the load medallion was designed around.

The deeper reason matters more than the surface fit. The discipline medallion enforces — clean boundaries between raw evidence, conformed intermediate, and business-ready output — is the same discipline the agentic system requires from the underlying data engineering. The classifier needs to trace from a FAIL back through marts → intermediate → staging → source, with each layer meaning something distinct. A monolithic transformation cannot provide that; medallion specifically can.

### The three layers concretely

**Bronze — preserved raw.** One landing table per source, written as data arrives, never modified after. Columns match the source exactly — no renaming, no casting, no filtering. Metadata columns added: `_source_name`, `_ingested_at`, `_quarter_received`, `_file_hash`. Stored append-only, partitioned by ingestion quarter. If a source resends a quarter with corrections, append a new partition rather than overwriting. For this project: five tables (`bronze.source_a_raw` through `bronze.source_e_raw`) preserving whatever each source delivers, warts and all.

**Silver — staging and intermediate.** Staging models (`stg_source_a` through `stg_source_e`) do per-source cleanup that doesn't depend on any other source: type casting, column renaming to canonical names, isolating source-specific quirks, trivial filtering. No joins to other staging models, no cross-source logic, no joins to reference data. Intermediate models (`int_funds`, `int_investees`) do the conformance work where most of the real engineering sits: identifier reconciliation across sources, effective-date alignment, overlap-and-precedence rules when sources disagree, unit and currency normalisation, and source provenance retention.

**Gold — the marts.** Two final tables (`funds`, `investees`) that the agentic system, business rules, and future reports consume. Clean, well-documented, well-typed, exposing exactly the columns and grain consumers need. Keep `_contributing_sources` provenance metadata on the marts as well as the intermediates — the classifier needs it to trace lineage when investigating a FAIL.

### Strict boundaries

No model in marts reaches back to staging directly. No staging model reaches into another staging model. The intermediate layer is the only place where data crosses source boundaries. This sounds bureaucratic until the first time a staging model is refactored and the impact is contained to one downstream intermediate model instead of propagating chaotically.

### Why not other methodologies

For defensive value when this choice gets questioned later:

- **Data Vault 2.0** (hubs, links, satellites) is more rigorous and is used in some major banks and insurers for similar reconciliation work. It is significantly more complex to design and maintain. Appropriate when regulatory burden exceeds what medallion gives you; almost certainly overkill at the current scale.
- **Kimball dimensional modelling** (facts and dimensions, star schemas) is not mutually exclusive with medallion — many shops produce dimensionally-modelled marts at the gold layer. If reporting needs grow complex, this is the natural extension within gold rather than a replacement for the architecture.
- **One Big Table** (wide denormalised tables) works for small teams with simple needs and struggles as relationships multiply. Doesn't fit the conformance work this project requires.
- **Streaming architectures** (Kafka, Flink, Materialize) serve real-time event processing, not batch quarterly financial data. Wrong shape for this workload.

### Label versus discipline

The vocabulary matters less than the discipline. If the same layering is adopted with the right rigour but called "raw / refined / curated," the benefits are identical. If the labels are adopted but staging models reach into other staging models, the benefits are zero. The value is in the layered separation; the labels are just the most common vocabulary for naming it — and there is real practical value in being on the dominant vocabulary, since every tool, every hire, and every document will assume it.

At the current research stage, the risk is not choosing the wrong methodology; it is spending too long on methodology rather than data. Plain medallion with sensible discipline gets 95% of the benefit. More rigorous patterns can be adopted later if needs grow; they should not be adopted preemptively.

**When to invest:** The structural refactor described in the "Transitioning From the Current State" section is the medallion refactor. Adopting the vocabulary and the layered discipline both happen at the same time, on the same work.

---

## 3. Idempotency and Replayability

Every pipeline should be runnable from any historical point and produce identical output. This is what makes the audit trail trustworthy and the agent's reproducibility property tenable.

Requirements:

- Transformations are deterministic functions of their inputs — no `CURRENT_TIMESTAMP` in derived columns, no `RAND()`, no "use whatever rates are in the FX table right now"
- Raw data is preserved at bronze with the as-of timestamp
- Reference data (FX rates, fund metadata, taxonomy mappings) is versioned with effective-from/effective-to dates so a Q1 recomputation uses Q1's FX rates, not today's
- Incremental models can be rebuilt from scratch and produce the same result as their incremental state

The test is whether the Q2-2024 pipeline can be rerun today and produce bit-for-bit identical Q2-2024 outputs. If it cannot, the audit trail is conceptually broken even if it looks complete on the surface.

**When to invest:** Reference data versioning matters now. Full pipeline replayability becomes critical as the quarterly pipeline takes shape.

---

## 4. Schema Contracts at Source Boundaries

A large fraction of business-rule FAILs originate not in transformations but in upstream sources changing without notification — a fund administrator adds a new field, renames a column, changes units, or quietly shifts the meaning of an existing field. For five sources unified into two datasets, this risk is multiplied: a change in any one source can ripple unpredictably.

Best practice: define a schema contract for every source (dbt has `model contracts` and source `freshness` checks; Great Expectations or Soda offer richer assertions) and fail loudly on contract violations at the bronze→silver boundary rather than silently propagating. The classifier's job becomes much easier when upstream changes produce a clear "schema contract violation in bronze" signal rather than a downstream "GAV reconciliation failed mysteriously" signal three layers later.

**When to invest:** When the quarterly pipeline is being built. The historical data is fixed in shape; future deliveries are where contracts pay off.

---

## 5. Reference Data and Slowly-Changing Dimensions

A lot of fund-data weirdness comes from reference data being mistreated. A fund's manager changes; an investee's classification gets updated; a currency pair gets retired. Handling these as overwriting updates causes historical data to disagree with itself.

Use slowly-changing dimensions (SCD Type 2 for things where history matters — fund classifications, ownership structures, valuation methodologies) and surface the effective-date dimension explicitly in any model that joins to reference data. When the classifier looks at a FAIL from Q2 and needs to understand which methodology was in force, it needs the Q2 methodology, not today's.

**When to invest:** Now, before any reference data gets overwritten in a way that breaks historical reconciliation. This is one of the cheapest disasters to prevent and one of the most expensive to undo.

---

## 6. Documentation That Lives Next to the Code

dbt's `description` fields on models and columns, plus the auto-generated docs site, are best practice for a reason that matters specifically here: the classifier reads these. Good column descriptions and model-level explanations are not just for humans — they are the context the agent consults when investigating FAILs.

Sparse or wrong documentation makes the classifier's job harder and hallucinated reasoning more likely. Treat documentation as part of system correctness, not as a nice-to-have. The discipline of "no model merged without a description" pays back disproportionately once an agent is reading the docs.

**When to invest:** As models are created or split. Easier to write fresh than to retrofit.

---

## 7. Testing with the Right Granularity at the Right Layer

A layered split with clean boundaries:

- **dbt tests at bronze→silver:** technical and structural correctness (types, nullness, uniqueness, referential integrity, freshness)
- **dbt tests within silver:** cross-model consistency (deduplication, foreign key resolution after conformance, row count stability)
- **Business rule engine on gold:** semantic checks like the GAV reconciliation rule and the surrounding constraint set

Do not try to do everything with one tool. Use Great Expectations or Soda for the rich business rules, dbt for the structural ones, and keep the boundary clean. The pattern of "test as early as possible" applies: a bronze-layer schema violation should fail bronze ingestion, not propagate to gold and trigger a business-rule FAIL that takes the classifier twenty tool calls to diagnose.

**When to invest:** dbt tests now, as the structural refactor happens. Business rule engine consolidation can come later as rules accumulate.

---

## 8. Data Observability Beyond Job Status

Basic pipeline observability (job scheduling, run status, SLA monitoring) is necessary but not sufficient. The project needs *data observability* — row counts over time, freshness, distribution shape, schema drift — because changes in these properties are often the upstream cause of rule FAILs and the classifier needs them as context.

Tools to consider: Monte Carlo, Anomalo, Elementary (integrates natively with dbt), or rolled-your-own with metric collection at every model. The classification "the GAV reconciliation FAIL coincides with a 12% drop in investee row count from supplier X" is much more useful than "GAV reconciliation FAIL," and the row-count observation requires the observability layer to exist.

**When to invest:** Light version (Elementary) now to start accumulating metric history. Heavier tooling once the quarterly pipeline runs and there is a meaningful time series.

---

## 9. Separation of Code and Configuration

Rules, thresholds, mappings, taxonomy definitions, and fund-specific exceptions should live as data or configuration, not be hard-coded into transformation SQL. Practical reasons:

- Changing a threshold should not require a code deploy
- A fund-family-specific exception should be addable without touching the rule's logic
- The classifier should be able to point at "this fund family has an exception registered in the config" rather than reading code to find it

Configuration-as-data also gives the same versioning property as code (configs go through PRs, stored in Git) without conflating engineering changes with business-rule changes.

**When to invest:** As rules are extracted from the monolithic SQL and given their own definitions. Doing this from the start of the rule engine is cheaper than retrofitting.

---

## 10. Cost Awareness

Query cost on modern warehouses (Snowflake, BigQuery, Databricks) accumulates faster than expected. For the agentic system, each classifier and proposer cycle can drive nontrivial compute — the sandbox runs SQL against the warehouse to verify proposed rules — and untuned models become surprise bills.

Practices:

- Monitor cost per dbt model and per business-rule run
- Flag any model whose cost grows nonlinearly with data volume
- Pre-aggregate where possible
- Use clustering and partitioning thoughtfully
- Treat very-expensive models as design smells rather than acceptable status quo

**When to invest:** Light monitoring now; serious optimisation once the agentic system is running and producing meaningful warehouse load.

---

## Transitioning From the Current State

The current research codebase is a single SQL document per table — updated reactively as data issues surfaced, operating on all five sources simultaneously. The natural question is whether to refactor toward the structure described above now, or wait until the research stabilises.

The framing of the dilemma — refactor now and risk encoding bad logic, or wait and suffer through the mess — assumes that refactoring locks in current behaviour. It doesn't. Refactoring *exposes* current behaviour. The giant SQL document is what hides bad logic, by burying it inside a dense, undifferentiated transformation where nobody can see what each piece is doing. Decomposing it into staged models doesn't encode anything new; it makes visible what was already there. That visibility is the precondition for finding the hidden issues already known to exist, not an obstacle to it.

So the real question is not "refactor or wait" — it's "structural refactor or semantic refactor," and the answer is different for each.

### Structural Refactor: Do Now

A structural refactor decomposes the giant SQL into staged models without changing what the SQL does. Every CTE becomes its own model. Every `CASE` block lives in an intermediate. Per-source logic gets split out before the conformance step. The marts that come out the other end produce identical output, row for row, to what the giant SQL produces today.

Three reasons to do this at the current stage:

First, the agentic system cannot work well against a monolithic transformation. The classifier's job is to point at "this FAIL came from this calculation, in this layer, drawing from these inputs." On a giant SQL blob, the answer is "the calculation is somewhere in the 2,000-line SQL document, drawing from all five sources simultaneously." The bundle becomes uninformative. Whatever effort goes into the agentic system is bounded above by the legibility of the data engineering it sits on top of.

Second, the quarterly pipeline cannot be built on top of a monolithic SQL document in any practical sense. A quarterly pipeline needs to run incrementally, recover from partial failures, recompute selectively, and accept new data without rebuilding everything. Those properties require decomposition. The structural refactor is happening regardless; the question is whether before or after more research code, agentic infrastructure, and documentation accumulate around the current mess. Sooner is cheaper.

Third, the act of decomposition is the cheapest, most thorough audit of the existing logic available. Every time a CTE is split into its own model and given a one-line description of what it does, an assumption that is currently implicit gets articulated. Half the bugs that surface during projects like this surface during decomposition — not because the refactor introduces them, but because previously nobody was looking at any individual piece carefully enough to notice. For a research-stage project with known-incomplete data quality, surfacing hidden issues is not a side effect; it is the most valuable output of the refactor.

### Semantic Refactor: Wait

A semantic refactor changes what the logic does — fixes bugs, adopts better methodologies, restructures business definitions. This is where the "encoding bad logic" risk genuinely applies, and where it pays to wait until the research stabilises.

The discipline: during structural decomposition, do not fix anything semantically. If the SQL has a hack where it casts a string to a float in a way that looks suspect, the refactored version should have the same hack in the same place, with a comment flagging it for later review. Resist the urge to clean up while reorganising. Doing so converts a low-risk reorganisation into a high-risk rewrite.

The boundary: structural changes preserve output bit-for-bit; semantic changes deliberately do not. Any change where the output diff is non-empty is a semantic change, and those wait.

### How to De-risk the Structural Refactor

The way to make a structural-only refactor safe is straightforward but rarely done well:

Snapshot the current outputs of the giant SQL for every quarter — all 17 from Q4 2022 to Q4 2026 — before touching anything. These snapshots are ground truth. After every structural change to the refactored version, re-run and compare. Any non-zero diff means the refactor changed behaviour, and the fix goes to the refactor, not the original. Continue until the refactored chain produces byte-identical output to the original SQL across all quarters. Only then is the structural refactor complete.

This is more disciplined than the typical "rewrite and hope for the best" pattern, but it is the discipline that makes refactoring safe. Inability to reproduce the original output exactly from the refactored chain is the failure mode the "encoding bad logic" worry is actually about — and snapshot-diff testing is what catches it.

### If Bandwidth is the Real Constraint

The "research is incomplete" framing sometimes hides a different concern: nobody on the team has the bandwidth to refactor while continuing the research. If that is the real constraint, the move is a *minimum-viable refactor* — decompose just the parts the agentic system needs to reason about, leave the rest as a single block, and decompose further as bandwidth allows.

The highest-value first chunk is the bronze→silver split: separating each source's staging logic from the conformance step. This alone gives the classifier most of what it needs to point at "the issue came from supplier X" rather than "the issue is somewhere in the unified transformation." It is also the smallest unit of refactor that meaningfully unlocks the rest of the architecture in this document.

---

## Tying It Together for This Project

The agentic system is a layer on top of these practices, and its quality is bounded by how well the underlying data engineering is done. A well-versioned, well-tested, well-documented, idempotent pipeline with clean lineage and rich observability gives the classifier good context to reason over and the proposer good signals to validate against. A messy pipeline produces noisy FAILs that even a perfect classifier would struggle with, because the underlying causes are themselves chaotic.

The leverage point: the better the underlying data engineering, the less work the agentic system has to do, and the more its proposed rules will reflect real business semantics rather than pipeline accidents.

The highest-impact investments before scaling up the agent layer are:

1. Layered transformations with strict boundaries so lineage is meaningful
2. Reference data versioning so historical reconciliations remain reproducible
3. Documentation good enough that the classifier reading it gets accurate context
4. Schema contracts at source boundaries once the quarterly pipeline begins

These four reduce FAIL volume, sharpen classifier accuracy, and improve the audit trail simultaneously.

---

## What Does Not Apply

For completeness, several common "best practices" don't fit this project's shape and can be deprioritised:

- **Real-time streaming infrastructure** (Kafka, Flink) — fund data is quarterly; the latency budget that justifies streaming doesn't exist. Batch is correct.
- **Data lakehouse vs warehouse debates** — for typed, tabular financial data with strong schema requirements, a modern warehouse is the right substrate. Lakehouse advantages mostly matter for semi-structured data and ML workloads, neither of which is the primary load here.
- **Feature stores** — the project is rule-based reconciliation with agents on top, not real-time ML. A feature store is unnecessary infrastructure.
- **Data mesh / microservices for data** — the per-domain ownership pattern matters at very large scale and is mostly overhead for small teams.
