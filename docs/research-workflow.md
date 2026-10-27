# Evidence-gathering research

The calculation planner uses MODEL, not CHAT_MODEL, to discover gaps, queue
acquisition, validate join plans, register measurements and finish its objective
review. Existing deterministic sport metrics remain preferred. No hosted sandbox,
new service, arbitrary SQL, shell, URLs or model-specified paths are exposed.

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
An opt-in live-source check on 2026-10-27 acquired isolated 2025 snapshots and
executed direct-key measurements for all four sports, including native NBA Stats
boxes and selected-game opponent context for CFB/soccer. See
[the live-source acceptance results](research-source-validation.md). This does not
certify other seasons, competitions, crosswalks, or unrecorded lineup intervals.
Live-model and frozen-installer verification remain separate from these checks.
