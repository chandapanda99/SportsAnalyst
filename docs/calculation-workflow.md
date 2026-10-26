# Interpreter-first calculations

NFL overall-offense EPA runs now include a deterministic exclusive accounting
breakdown before narrative generation. Turnovers (interceptions or lost fumbles)
take precedence, then sacks, pass-coded plays, run-coded plays, and other plays.
Scrambles stay run-coded. Each category's EPA sum is divided by the entire
window's qualifying-play count. The difference between windows is a contribution
to the overall EPA/play change, not within-category efficiency or a causal effect.
The sum must reconcile at full precision. Missing classification fields or values
produce a disclosed gap, not invented zeroes. Unequal window samples are allowed.

The first milestone adds accounting evidence, a signed contribution chart, and
offline report support. Older NFL offense reports lacking accounting are prepared
again when a phase/contribution follow-up requests it. Other follow-ups still reuse
their parent evidence. Arbitrary Python execution is not implemented.

## Free-form question planning and scoped measurement

The planner now interprets the actual question rather than dispatching through a
fixed intent/metric mapping. It must record objectives, evidence already available,
required data, proposed calculations and limitations, then finish a coverage review
mapping every objective to known evidence IDs or an explicit unresolved reason.
These decisions are model assessments, not proof that all relevant data was found.

Schema discovery exposes installed dataset IDs, columns, coverage and attribution
in the requested seasons/competition and permitted partitions, without paths.
Full-season investigations can query intermediate years using `season:YYYY`;
other designs retain only their explicitly selected windows.
The aggregation tool accepts recorded columns, up to three grouping fields, eight
measures (count/sum/mean/min/max/distinct non-null count), and eight literal filters.
No SQL, file paths, arbitrary Python, downloads, mutations or new permissions are
available. Required data that is not installed is reported as a gap, not fetched
automatically by this planner. Existing metric preparation continues unchanged.

The host enforces subject attribution and window/season compatibility. Unknown
attribution, named segments without verified attribution, and non-NFL season-type
restrictions that cannot be verified are rejected, not silently broadened. This
generic tool does not yet perform schedule joins, cross-table joins or resolve
new model compatibility definitions. Existing sport-specific metrics remain the
preferred option for those cases. Raw scoped rows are NOT automatically the same
sample as a predefined metric; the planner must state qualifying filters.

Each query reads only needed columns with a lazy subject/time predicate and
rejects slices over 200000 rows or results over 100 groups. There are at most 16
queries per stage and 128 additional measurement records. Numeric sums of entirely
missing values remain null. Results include non-null counts, row counts, window,
source checksum, filters and groupings. Queried manifests are included in saved
reports. Derived arithmetic may use measured results by their evidence IDs.
All objective reviews are included in the report model's analytical context;
unresolved objectives are also stored as report caveats. Rejected query arguments
are returned as errors so the model can revise them within the graph budget.

The shared optional calculation stage uses MODEL (never CHAT_MODEL), LangChain's
agent loop, and CodeInterpreterMiddleware. It can inspect bounded existing evidence
and compose basic arithmetic over known evidence IDs. Registration independently
recalculates the expression in a small AST evaluator; it never executes Python eval.
Arithmetic validation does not prove compatible samples, units, statistical
meaning, or causation. These remain explicit caveats for the narrative reviewer.
No raw SQL, paths, network, package installation or dynamic subagents are exposed.

Limits: 32 MiB JavaScript heap, 3-second eval timeout, 16 bridged calls per eval,
20 graph recursion steps, eight accepted derived arithmetic records, and 24 registration
attempts. These are not a global LLM wall-time or billing cap. Code and tool
receipts from a completed stage are saved in ToolExecutionRecord before the
citation ledger is built. Partial calculations from a failed stage are discarded.
Missing model configuration skips composition; interpreter failures add a report
caveat without blocking deterministic analysis. CALCULATION_INTERPRETER_ENABLED=false
disables optional composition, not tested NFL accounting.

## Installation and verification

Run `uv sync` with your usual extras. The lockfile includes langchain-quickjs,
quickjs-rs and wasmtime. The beta middleware and dependency versions are locked for
reproducibility. PyInstaller collects the QuickJS Wasm resources and runtime DLLs;
the frozen smoke test actually executes JavaScript. Rebuild installers to include
these dependencies. This does not resolve Windows certificate/policy trust, and
the installer still needs a signed build and a clean-machine smoke test.

The implementation is local and needs no sandbox service. Run the offline feature
tests in tests/test_calculations.py. A live MODEL end-to-end run remains a separate
verification step; offline tests use a scripted model but execute the real QuickJS
middleware and host-tool bridge.

## Optional LangSmith sandbox walkthrough

Verified against https://www.langchain.com/pricing on 2026-10-26: the Developer
plan includes 5 LCU of compute/memory and 1 LSU of storage sandbox usage per month,
limited to 10 sandboxes. This is a metered allowance, not unlimited free hosting;
check your workspace's current billing terms before creating resources.

1. Sign into https://smith.langchain.com, select/create your workspace, and open
   Sandboxes. Confirm Developer-plan access and remaining allowance in billing.
2. Create an appropriately scoped API key in settings. Never commit it, upload it
   here, include it in a sandbox, or distribute it with a Windows installer.
3. Set LANGSMITH_API_KEY privately in your local .env. Set LANGSMITH_ENDPOINT to
   your regional API endpoint (GCP US: https://api.smith.langchain.com).
   If needed, set LANGSMITH_WORKSPACE_ID to the intended workspace ID. On a cloud
   deployment put these values in deployment secrets, not frontend configuration.
4. From the repository root run:

   `.venv\Scripts\python.exe scripts\check_langsmith_sandbox.py`

   This creates a temporary sandbox, checks synthetic Python arithmetic, and
   deletes it with a context manager. It uploads no sports data and calls no LLM.
   If provisioning/disconnection interrupts cleanup, inspect Sandboxes and delete
   any leftover resource yourself; do not assume an idle timeout prevents charges.
5. Confirm deletion and usage in the dashboard. Before expanding to real data,
   build a pinned scientific-library snapshot and verify effective network policy,
   protected inputs, resource limits, result validation and cleanup under failures.

Default restricted egress is NOT no internet. LangSmith's organization-managed
allowlist may override caller access_control settings. Confirm deny-all support
for your account before relying on this provider for untrusted custom execution.
See https://docs.langchain.com/langsmith/sandbox-auth-proxy and
https://docs.langchain.com/langsmith/sandbox-sdk.

This script verifies service access only. Adding the key does NOT enable a hosted
Python fallback in the app. A provider-independent sandbox escalation adapter is
future work; this release implements the Interpreter-first milestone instead.
