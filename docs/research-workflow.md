# Analysis and evidence workflow

The current prompt contract version is recorded in synthesis trace metadata. Shared
rules, sport/domain guidance and reviewer requirements live in
`src/sports_analyst/analysis/instructions.py`; agent construction is in
`src/sports_analyst/analysis/agents.py`.

Every coordinator/specialist receives the same analytical contract. The coordinator
also receives reviewer checks, including direct follow-ups without specialists.
`inspect_analysis_context` supplies selected subject/windows, current timestamp,
registered metric definitions and the acquisition dates/coverage of evidence sources.
Unknown definitions or completeness remain unknown. Context is not itself a citation.
Comparison evidence includes both sample counts where the analytics provide them;
play-row counts must not be mistaken for a metric's non-null denominator.

`MODEL` performs planning, calculations, specialist review and evidence synthesis. `CHAT_MODEL`, when configured, edits only the
validated draft's wording and must preserve numbers, denominators, qualifications,
sport terminology and measured-versus-interpretive status.

## Question planning and calculation

The planner records the question's objectives, existing evidence, required data
and calculations, then maps every objective to evidence IDs or an explicit gap.
Planner and writer use a paginated metric-family index; a short initial payload
is not treated as the entire evidence registry. Existing deterministic metrics
remain preferred.

Scoped aggregation accepts recorded columns, up to three grouping fields, eight
measures and eight literal filters. Count, sum, mean, min, max and distinct
non-null count retain their denominators. Entirely missing sums remain null.
Full-season investigations may query intermediate years with `season:YYYY`;
other designs retain their selected windows. Unknown attribution and unverifiable
season/segment restrictions are rejected rather than broadening scope.

Existing sport metrics and raw scoped rows can have different eligibility rules;
the planner must specify qualifying filters. Invalid operations return actionable
field/operator errors. Objective reviews enter the writer's analytical context;
unresolved objectives become caveats. The writer must cite evidence for covered
objectives, with one repair attempt before deterministic fallback when citation
coverage fails. These checks do not establish semantic entailment.

### NFL phase accounting

NFL overall-offense EPA runs include a deterministic exclusive accounting
breakdown before narrative generation. Turnovers (interceptions or lost fumbles)
take precedence, then sacks, pass-coded plays, run-coded plays, and other plays.
Scrambles stay run-coded. Each category's EPA sum is divided by the entire
window's qualifying-play count. The difference between windows is a contribution
to the overall EPA/play change, not within-category efficiency or a causal effect.
The sum must reconcile at full precision. Missing classification fields or values
produce a disclosed gap, not invented zeroes. Unequal window samples are allowed.

## Interpreter execution

The shared optional calculation stage uses MODEL (never CHAT_MODEL), LangChain's
agent loop, and CodeInterpreterMiddleware. It can inspect bounded existing evidence
and compose basic arithmetic over known evidence IDs. Registration independently
recalculates the expression in a small AST evaluator; it never executes Python eval.
Arithmetic validation does not prove compatible samples, units, statistical
meaning, or causation. These remain explicit caveats for the narrative reviewer.
No raw SQL, paths, network, package installation or dynamic subagents are exposed.

Limits: 32 MiB JavaScript heap, 3-second eval timeout, 16 bridged calls per eval,
32 graph recursion steps per planning round, eight accepted derived arithmetic records, and 24 registration
attempts. These are not a global LLM wall-time or billing cap. Code and tool
receipts from a completed stage are saved in ToolExecutionRecord before the
citation ledger is built. Independently validated measurements survive later stage failures.
Failures save a separate failed-stage audit containing the error type, plan,
review, tool receipts and retained evidence IDs. Raw provider exception text is not
persisted in this audit. Existing evidence remains usable, but the report summary
and caveats explicitly identify partial analysis due to execution failure, rather
than claiming the source data are absent. Missing model configuration skips
composition. CALCULATION_INTERPRETER_ENABLED=false
disables optional composition, not tested NFL accounting.

### Runtime dependencies

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

## Discovery and contracts

`inspect_scoped_datasets` returns installed manifests and declared acquisition
capabilities, including reference tables/provider channels. It is paginated and
has dataset-name filtering. Column previews are deliberately short:
`inspect_dataset_schema` provides full pagination and targeted column-name search.
`inspect_dataset_profile` audits exact snapshot schema/key counts without returning
raw records or paths. A declared contract or unique snapshot key is not proof of
historical coverage, compatible identities, or a usable statistical method.
Installed manifests and acquisition capabilities have independent pagination
(`next_offset` and `capability_next_offset`). Capabilities include adapter-owned
dependency packages and distinguish downloadable packages from installed-only
packages. Their existence is never reported as verified upstream availability.

The registry describes grain, source namespaces, keys and temporal restrictions.
Soccer `play_by_play` is fixtures; roster listings are not proof of appearances.
NBA ESPN/native identifiers are separate. Weekly NFL membership is joined on
recorded season/type/week/player/team, never a current profile's latest team.
Native NBA player bases require a verified player crosswalk.
NFL PFR identities similarly use the recorded player-reference mapping. Regular
season/date attribution uses the sport's verified schedules where necessary;
conflicting scope facts across partitions are rejected rather than unioned.

## Acquisition and worker resumption

`prepare_analysis_data` takes an AcquisitionPlan: objective, dataset, season,
purpose (`primary` or `context`), optional team_id/fields, expected reuse, and the current round.
It queues work and returns immediately. After the agent ends its turn the existing
analysis worker downloads/prepares data outside QuickJS, returns receipts, and
resumes the planner. No synchronous browser request waits for that preparation.
The queue, dependency decisions, running/completed entries and receipts are
persisted before the worker proceeds. Dependencies run in topological order;
repeated delivery reuses completed decisions. A replacement worker resumes pending
entries using durable leases and the original cumulative budget. Server settings
control the round limit (default two, maximum eight); it is not hardcoded in the
agent's plan schema or prompt.

NFL/NBA use bounded streaming of the published assets behind their existing
loaders; CFB/soccer use team/player endpoints and shared game caches. Native NBA
research assets use the app's END-year convention and validate recorded season
stamps. Current primary preparation formats are not migrated or rewritten.
New bulk research snapshots have immutable paths rather than overwriting older
downloaded bytes. Native NBA bases without a preserved source-season stamp must
be reacquired through this verified adapter before new joined research; old saved
reports are not relabelled or rewritten.
CFB player acquisition follows verified athlete game logs across schools. Context
schools/opponents must be established from the selected-season records; they
cannot become primary subjects. Requests never recursively fetch their libraries.
CFB/soccer opponent enrichment fetches summaries only for verified completed games
already in the primary selection. Per-game context is shared and then consolidated
into a separate, immutable `research_context` snapshot. Successful games survive
partial failures and are reused on retry. Unsupported game-scoped packages return
an explicit limitation rather than falling back to the opponent's entire season.

CFB modeling requires installed, content-hashed model artifacts. Agent instructions
cannot install/download models. Requested recorded rendering fields can use the
existing NCAA field policy only when enabled and usage-confirmed. Secondary
transports are budgeted too; incompatible CFBD models are not merged into primary
EPA/WPA. Provider selection and usage confirmation remain operator controls.

Server-side settings (environment variables use their uppercase names):

| Setting                     | Default                                   |
|-----------------------------|-------------------------------------------|
| `RESEARCH_ROUNDS`           | 2                                         |
| `RESEARCH_PACKAGE_ATTEMPTS` | 16                                        |
| `RESEARCH_SOURCE_REQUESTS`  | 250                                       |
| `RESEARCH_TRANSFER_BYTES`   | 2147483648 (2 GiB)                        |
| `RESEARCH_ELAPSED_SECONDS`  | 600                                       |
| `RESEARCH_WORKING_BYTES`    | 536870912 (512 MiB projected joined data) |

`DATASET_SYNC_CONCURRENCY` remains the provider concurrency control. Budget state
is persisted under the investigation identity and protected with existing local/
durable leases. Network redirects/retries count as requests; cached source reads
do not. Bytes are reserved before reads, so interruptions conservatively retain
reservations. Time is checked at network/stage boundaries, not by forcibly killing
native code. JSON responses also have a 16 MiB bound. Exhaustion returns a specific
Data Management/retry action; optional absence does not become an empty success.

## Join execution

`discover_relationships` returns candidate relationship IDs. A JoinPlan specifies
an objective, base dataset/window/grain, up to four steps, fields, filters,
pre-aggregations, grouping and measures. Steps use relationship IDs, never free-form
key mappings. `validate_join_plan` saves a plan ID; `execute_joined_aggregate`
rechecks source checksums and cardinality before registering evidence.

- Enrichment is observation-preserving. Duplicate right keys reject enrichment.
- `exists`/`not_exists` select base observations without child fan-out.
- `preaggregate` reduces child records to connecting keys before joining.
- Crosswalks must be unfiltered, unambiguous enrichments; the model cannot select
  one convenient mapping or average conflicting identities away.
- Opponent roles use recorded defensive-team IDs or a verified home/away bridge.
  Acquiring opponent context cannot replace the selected team's primary rows.
- Native NBA `order_index` can match verified same-version, same-game/period
  possession bounds using closed intervals. Overlap, invalid ordering or missing
  axes reject the join. Native per-action lineup snapshots support exact matches;
  season lineup totals do not become intervals. ESPN action numbers/clocks are not
  silently substituted for NBA Stats ordering.
- Pregame interpretations remain blocked without verified publication timing.
- Missing policy is explicit: `preserve`, `matched`, or `strict`. Missing numeric
  values are not zero. Audits retain input/qualifying rows, per-step coverage and
  measurement-specific non-null denominators.
- Rates use `op=rate`, `field` for the recorded numerator, and `denominator` for
  its compatible counter. The host permits defined counter pairs, uses the same
  finite, nonnegative observations for both sums, and retains the sums and paired
  coverage. A zero total denominator yields no rate. Unsupported pairs or source
  aliases are rejected; missing counters never become a reported zero.

Legacy schedule lookups compile to a strict join plan. Queries project required
columns, partition by game, reject partitions over 200000 rows, and spill projected
intermediates to temporary Parquet. Final aggregation is over observations, not
averages of partition means or sums of partition distinct counts. Output is capped
at 100 groups/128 new evidence records, with a shared 16-query/profile budget.
Limits return errors, not truncated findings. Repeated game totals cannot be summed
as play/player measures. CFB modeled comparisons check recorded model identities.
Each measurement also records a source-specific definition, units, grain,
eligibility and population rules, provider and package/processing versions.
Cross-window registration checks those definitions before accepting a comparison.
Unknown units remain explicitly source-specific rather than being guessed.

## Evidence, replay and reporting

Plans, source hashes/manifest IDs, contract versions, coverage audits, aggregates
and acquisition receipts use local/durable research artifacts. Cached joined
results are reused only after input checksum verification. Saved reports retain
the full execution receipt, and all source manifests enter the evidence ledger.
Individually validated results survive later research-stage failures; the report
and follow-up are then explicitly partial. Derived arithmetic remains independently
checked, not automatically causal or statistically valid.
A durable measurement journal publishes evidence before report construction and
restores it after worker replacement. Recovery rechecks exact approved inputs and
contracts; changed inputs invalidate the affected results explicitly. Later
enrichment does not silently change a previously approved plan's inputs. Contract,
relationship and crosswalk-processing changes invalidate cached execution even
when the underlying Parquet checksum is unchanged.

New measurements are discoverable by planner/writer, charted with independent
metric scales, exported through existing report evidence, and reusable by
follow-ups. Follow-ups may research genuinely unanswered objectives while keeping
their parent evidence immutable. Existing saved reports are not retroactively
rewritten. Restart the backend/rebuild desktop bundles to pick up these changes.

Offline feature tests use scripted models with real QuickJS and host execution.
Synthetic fixtures verify joins, overlap/duplicate rejection, transfers, budgets,
cloud/local replay and failure recovery; they do not certify source availability.
The four-sport feature flow covers two comparison windows, queued acquisition,
registered measurements, charts, citation resolution, worker-replacement recovery
and follow-up reuse without modifying parent evidence. Opponent-context tests
verify unrelated and future games are excluded and incomplete downloads resume.

## Verification

### Model evaluation

The retained high-level tests exercise actual tool and prompt construction for NFL
receiving, NBA defense and soccer scoring, with unequal samples, incomplete coverage,
missing values, counter-signals and unsupported tactical questions. Calls are mocked:
these are wiring/contract regressions, not proof of model factual accuracy.

For live model evaluation, replay these cases with captured evidence and the configured
analysis model, reviewing initial and follow-up outputs separately. Model calls incur
provider usage and are not part of the default test suite. Use these acceptance criteria:

| Scenario                                     | Required behavior                                                                               |
|----------------------------------------------|-------------------------------------------------------------------------------------------------|
| NFL receiving improvement with fewer targets | Separate workload and efficiency; do not infer separation from yards/target.                    |
| NBA lineup improvement                       | State unit/sample context; do not credit an individual or infer assignments from lineup rating. |
| Soccer goals rise while xG falls             | Preserve contradictory signals; compare covered matches and avoid finishing-skill forecasts.    |
| Missing metric                               | Explicitly unavailable, never zero or estimated.                                                |
| Unequal samples or partial coverage          | Identify the relevant restriction without declaring causal/statistical certainty.               |
| Endpoint-only range                          | Do not invent intermediate-season results or a continuous trend.                                |
| Conversational rewrite                       | Preserve conclusions and material restrictions; add no new facts or mechanisms.                 |

Score each response for numerical fidelity, citation entailment, scope/coverage fidelity,
sport terminology, causal restraint and directness. Any invented number, unsupported
tactical assertion, or source/window mismatch fails the case. Record prompt version,
model/version, source snapshot and reviewer rationale when comparing runs in LangSmith.

Citation schema validation checks that references exist; it does not establish semantic
entailment. Reviewer prompts and structured output do not replace independent evaluation.

### Sampled source acceptance (2026-10-27)

This source-only check made no model calls. Generated captures, manifests,
checksums and results are local artifacts under
`data/research-source-validation-20261027/`, not bundled documentation. The isolated
catalog does not replace the primary library. The following are sampled results,
not guarantees for other seasons or competitions.

| Selected source sample                                                       | Base records | Matched records |     Non-null measured values |
|------------------------------------------------------------------------------|-------------:|----------------:|-----------------------------:|
| NFL, Chicago, 2025 plays with FTN charting                                   |        1,637 |           1,602 |             1,602 EPA values |
| NBA, Boston, 2024–25 ESPN player/team boxes                                  |        1,272 |           1,272 |            977 points values |
| NBA, Boston, 2024–25 NBA Stats player/team boxes                             |        1,272 |           1,272 | 1,272 recorded points values |
| CFB, Iowa State, 2025 player/team game statistics                            |          127 |             127 |       15 passing-yard values |
| Premier League, Arsenal, 2024–25 team statistics with pre-aggregated lineups |           38 |              38 |               38 shot totals |

Every join preserved its base observation grain. Missing context and non-null
measurement coverage remain distinct. All audited primary snapshot keys were
unique and non-null. These are listed box-score records, not necessarily player
appearances. The ESPN/native NBA sources returned the same 10,697 team points,
but differed in null versus recorded-zero player entries. Their denominators must
not be interchanged for appearance-based averages; check minutes/participation.

Selected-opponent acquisition also passed against the real catalog: CFB retained
9 player-game records for one opponent's game; soccer retained 2 matches for one
opponent. It reused already acquired summaries without fetching either opponent's
entire season. The full primary samples remained unchanged.

The ESPN Core xG probe covered only Premier League events `704380` and `704656`.
All four team statistics responses supplied conventional goals/shots but no
expected-goals fields recognized by the source parser. The raw responses are
retained under the isolated soccer Core-statistics cache. This is a two-fixture
result, not evidence that historical xG is absent everywhere.

Replay the source-only check explicitly:

```powershell
.venv\Scripts\python.exe scripts/validate_research_sources.py --run-live-sources --output data/research-source-validation-20261027
```

It honors `DATASET_SYNC_CONCURRENCY`, persists acquisition budgets, and reuses
successful snapshots. A fresh output directory performs fresh acquisition. Each
sport's transfer cap is at most 512 MiB and the configured request/time limits
remain in force. It never enables a new provider or uses model credentials.

This run does not validate live-model reasoning, additional historical seasons,
all FBS/FCS conferences, every soccer competition, cross-provider athlete/game
crosswalks, lineup intervals, pregame publication timing, or the frozen installer.

### Optional sandbox access check

The app does not implement a hosted Python fallback. LangSmith credentials alone
do not enable one. For a separate, opt-in service-access check, configure private
`LANGSMITH_API_KEY`, `LANGSMITH_ENDPOINT` and (if needed)
`LANGSMITH_WORKSPACE_ID`, then run:

```powershell
.venv\Scripts\python.exe scripts/check_langsmith_sandbox.py
```

The script creates a temporary sandbox, checks synthetic arithmetic and attempts
cleanup; it uploads no sports data and calls no LLM. Confirm current access,
pricing, effective network policy and deletion in your workspace before use.
Service access does not establish safe custom execution or enable an app feature.
See the [Sandbox SDK documentation](https://docs.langchain.com/langsmith/sandbox-sdk).
