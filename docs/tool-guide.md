# Sports Tool Guide

This guide describes the analytical tools and capabilities exposed across NFL, NBA, college football and soccer. It distinguishes implemented investigation behavior from catalog
entries that reserve the intended product surface.

## Discovering capabilities

The frontend reads sport-specific options instead of hard-coding one league:

|                  Endpoint                  | Purpose                                                           |
|:------------------------------------------:|-------------------------------------------------------------------|
|             `GET /api/sports`              | Sport labels, availability, and capability status                 |
|     `GET /api/sports/{sport}/options`      | Seasons, subjects, periods, domains, metrics, and diagnostic cuts |
| `GET /api/sports/{sport}/metrics/{metric}` | Metric definition and interpretation                              |
|      `GET /api/sports/{sport}/tools`       | Tool catalog for the sport                                        |
|     `GET /api/sports/{sport}/players`      | Searchable player options when supported                          |

There is no public generic “execute tool” endpoint. Investigations select and run the plugin behavior supported by the current analysis service. A tool appearing in the
catalog does not necessarily mean that it produces a separate execution record yet; the status tables below call out that distinction.

### Guided workbench

The options response includes `data_setup`: `required_datasets`, `recommended_datasets`, source `descriptions`, a `label`, and a summary `description`. Each plugin owns its
quick-setup policy. Older option payloads remain supported through optional frontend metadata and a default backend model; investigation payloads and stored reports are
unchanged.

The workbench starts with recommended metrics and exposes the full catalog through **Customize metrics**. **About** loads the metric-definition endpoint for interpretation,
qualifying sample, directionality, formula, and limitations. **Optional breakdowns** is the user-facing name for diagnostic cuts; an empty selection retains the service's
automatic recommendations.

The **Analysis brief** checks required source coverage, subject, comparison periods, metrics, and question before enabling **Run analysis**. A readiness item focuses the
relevant section. Data downloads require an explicit click, with local installation status displayed separately from package selection.

Reports display the answer and selected metric changes first, automatically load the first finding's supporting evidence, and place evidence inline on narrow screens. Raw
source references, caveats, and executed tools remain accessible through expandable details. “Reference period” in the UI corresponds to `baseline` in existing APIs and
evidence records.

## Shared investigation contract

Every investigation identifies:

- a `sport` (`nfl`, `nba`, `cfb` or `soccer`);
- a subject with a stable `id`; all four sports accept `team` or `player` subjects;
- two analysis windows;
- a plugin-defined domain and selected metrics;
- optional diagnostic cuts and a natural-language question.

Legacy NFL payloads remain valid: a missing sport defaults to `nfl`, a missing explicit subject is inferred from `scope.team`, and legacy `baseline_season` /
`comparison_season` values become complete-season windows. Current NFL windows use the inclusive `weeks` pair directly; NBA windows add a normalized `segment` value.

Dataset identity includes sport, dataset, season and, where applicable, competition, partition and provider/version. Internal play-by-play queries always include the sport boundary, so an NBA
investigation cannot read NFL data and vice versa.

### Shared representative-evidence selector

Football and NBA representative plays use the deterministic, versioned `diverse-v1` selector. Candidates from the baseline and comparison windows are considered together, then up to four distinct
items are selected per window in this stable role order:

1. `typical` — closest to the ordinary recorded outcome for that window;
2. `metric_example` — especially relevant to the selected metric;
3. `supports_change` — aligned with the measured direction between windows;
4. `counterexample` — runs against that direction.

The selector prefers different games and reduces the score of repeated event types, opponents, and periods. Stable candidate keys provide deterministic tie-breaking. A sparse
candidate pool produces fewer items rather than duplicate or invented evidence.

Each `PlayEvidence` record carries `window`, `evidence_role`, `selection_reason`, `selection_metric`, `candidate_pool_size`, and `selector_version`. Reports group this
evidence by window and expose the selection reason alongside the sport-specific visualization.

## NFL plugin

NFL remains the most complete analysis plugin. It supports team-centered passing, rushing, and total-offense investigations plus player-centered quarterback, receiving, and
rushing investigations over full seasons, week ranges, and before/after week windows.

### NFL minimum samples

- Team investigations require at least 30 qualifying plays in every comparison window and every season in a full-season range.
- Player investigations use every attributed play available. Windows below 10 plays are reported as highly uncertain, and metrics are omitted only when their required values
  are unavailable. Quarterback reports can supplement sparse play-by-play with compatible synced weekly player, Next Gen passing, and PFR passing statistics.
- A subgroup or diagnostic split requires at least 10 plays.

Small groups can still appear as descriptive context, but they are not promoted as reliable findings.

### NFL metrics

|  Domain |        Metric         | Definition                                                  |
|--------:|:---------------------:|-------------------------------------------------------------|
| Passing |   EPA per dropback    | Total passing EPA divided by qualifying dropbacks           |
| Passing |     Success rate      | Share of dropbacks with positive EPA                        |
| Passing |         CPOE          | Mean completion percentage over expected                    |
| Passing |  Explosive pass rate  | Share of dropbacks gaining at least 20 yards                |
| Passing |    Yards per play     | Yards gained divided by qualifying dropbacks                |
| Passing |       Sack rate       | Sacks divided by dropbacks                                  |
| Passing |   Interception rate   | Interceptions divided by dropbacks                          |
| Passing | Air yards per attempt | Air yards divided by attempts                               |
| Passing |  YAC per completion   | Yards after catch divided by completions                    |
| Rushing |     EPA per rush      | Total rushing EPA divided by qualifying rushes              |
| Rushing |   Rush success rate   | Share of rushes with positive EPA                           |
| Rushing |    Yards per carry    | Rushing yards divided by attempts                           |
| Rushing |  Explosive rush rate  | Share of rushes gaining at least 10 yards                   |
| Rushing |      Stuff rate       | Share of rushes stopped at or behind the line               |
| Rushing |    First-down rate    | Share of rushes gaining the yards required for a first down |
| Offense |     EPA per play      | Total EPA divided by qualifying offensive plays             |
| Offense |     Success rate      | Share of plays with positive EPA                            |
| Offense |    Yards per play     | Total yards divided by qualifying plays                     |
| Offense |     Turnover rate     | Turnovers divided by qualifying plays                       |

Metric metadata returned by the API is authoritative for exact labels, polarity, units, and availability.

### NFL analysis tools

|                                  Tool                                   | Current behavior                                                                                                                                        |
|:-----------------------------------------------------------------------:|---------------------------------------------------------------------------------------------------------------------------------------------------------|
|            `get_analysis_options`, `validate_analysis_scope`            | Discovers valid inputs and validates entities, fields, windows, and samples                                                                             |
|                         `compare_time_windows`                          | Computes the selected metrics for both windows and their changes                                                                                        |
|            `analyze_season_trends`, `analyze_weekly_trends`             | Produces season- or week-level aggregates and uncertainty                                                                                               |
|                          `rank_game_outliers`                           | Finds unusually strong or weak game performances                                                                                                        |
|                       `benchmark_against_league`                        | Compares the team with league and conference distributions                                                                                              |
|            `analyze_situational_split`, `analyze_game_state`            | Supports down, distance, field position, score state, personnel, formation, and related cuts when fields exist                                          |
| `decompose_metric_change`, `compare_play_mix`, `identify_change_points` | Describes mix, within-group performance, usage, and timing changes                                                                                      |
|                         `adjust_for_opponents`                          | Adds leave-one-game-out opponent-strength context                                                                                                       |
|                       `find_representative_plays`                       | Selects diversified, role-labeled plays from both windows using the shared evidence policy                                                              |
|                            `explain_metric`                             | Returns definitions, formulas, and interpretation guidance                                                                                              |
|                          `query_play_by_play`                           | Registered catalog capability backed by a constrained internal SQL helper; it is not a public execution endpoint or persisted investigation tool record |
|            `compare_player_windows`, `analyze_player_trends`            | Compares one quarterback, receiver, or rusher and records season-level trajectory evidence                                                              |
|                    `compare_player_published_stats`                     | Adds player-specific weekly, Next Gen passing, and PFR passing evidence when compatible synced rows cover both windows                                  |
|                   `find_player_representative_plays`                    | Applies the same two-window evidence policy to plays carrying the requested player identifier                                                           |

Supplemental NFL datasets enable extra context:

|       Dataset       | Adds                                        |
|:-------------------:|---------------------------------------------|
| Weekly player stats | Player production and contribution context  |
|    Participation    | On-field participation and personnel detail |
|       Rosters       | Player identity, position, and team context |
|      Schedules      | Game boundaries and opponent context        |

The supplemental catalog also includes `resolve_player`, `build_player_week_dataset`, `get_roster_context`, `analyze_starter_availability`,
`summarize_injured_or_inactive_players`, `compare_player_usage`, `analyze_position_group_availability`, `analyze_lineup_continuity`, `decompose_lineup_continuity`, and
`analyze_qb_receiver_pairs`. Dataset join tools cover Next Gen passing/receiving/rushing, participation, depth charts, FTN charting, PFR advanced statistics, and schedules.

Older tool aliases and legacy saved investigations are normalized at the service boundary so existing NFL history, exports, and follow-ups continue to load.

## NBA plugin

NBA v1 preserves the NFL investigation flow while using basketball-specific subjects, season segments, metrics, and evidence.

### Data and subjects

The default NBA sync uses published SportsDataverse bulk releases:

- play-by-play;
- schedules;
- team box scores;
- player box scores.

NBA seasons are stored by ending year and displayed as spans. For example, season `2026` is displayed as `2025–26`. The connector translates that canonical value to each
loader’s expected argument.

Both teams and players are primary subjects. The plugin exposes only the 30 current NBA franchises as team subjects and excludes All-Star, Rising Stars, and other event-team
records. Player options are resolved from synced data for those franchises. The frontend loads each sport's player list once and filters it locally by name, identifier, or
team as the user types. A player investigation normally includes all team stints in the selected period. Supplying `subject.team_id` limits a traded player to one stint.

### NBA periods

The plugin offers only segments whose boundaries can be validated against synced schedules:

- full season;
- regular season;
- playoffs;
- opening month;
- pre-All-Star and post-All-Star;
- post-trade-deadline;
- play-in;
- first round;
- conference semifinals;
- conference finals;
- NBA Finals.

Standard phases are derived from schedule fields and playoff labels. Non-schedule boundaries use a reviewed, versioned milestone table, currently covering ending seasons 2022
through 2026. The current before/after milestone design uses the All-Star boundary.

### NBA metrics

Estimated possessions use:

```text
FGA - offensive rebounds + turnovers + 0.44 × FTA
```

Team offensive and defensive ratings are points scored or allowed per 100 estimated possessions. Other team metrics cover shooting, playmaking, rebounding, and turnovers.
Player metrics cover scoring, shooting, playmaking, rebounding, a usage proxy, and plus/minus. Lineup ratings are possession-weighted when possession counts are present and
minutes-weighted only as a fallback. The plugin selects advanced-measure rows, one preferred per-mode, the requested regular-season/playoff phase, and one row per group ID.

Use `GET /api/sports/nba/options` and the metric-definition endpoint for the exact metrics currently exposed for each domain and subject type.

### NBA v1 execution status

|                       Capability                       | Status                                                                                    |
|:------------------------------------------------------:|-------------------------------------------------------------------------------------------|
|                 `compare_time_windows`                 | Implemented for team and player box-score metrics                                         |
|                `analyze_season_trends`                 | Implemented as a multi-season chart plus the two selected-window aggregates               |
|               Traded-player stint filter               | Implemented                                                                               |
|       `find_representative_possessions` behavior       | Implemented from both windows of synced play-by-play as part of the investigation         |
|                   Lineup comparison                    | Implemented when compatible lineup seasons are synced for both windows                    |
|   Local/live-derived V3 possession/lineup enrichment   | Implemented when matching rows are registered; no V3 bulk release is currently advertised |
|      `analyze_game_trends`, `rank_game_outliers`       | Executed for box-score analyses, with game variability and comparison-window extremes     |
|               `benchmark_against_league`               | Executed for team analyses when the comparison release contains league rows               |
|                 `adjust_for_opponents`                 | Executed as descriptive schedule context when opponent identities are available           |
|                `compare_shot_profiles`                 | Executed for shooting analyses from recorded play-by-play shot value/distance             |
|                 `compare_player_usage`                 | Executed for player analyses to separate minutes/involvement from efficiency              |
|              `analyze_lineup_performance`              | Executed with named units, minutes, possessions, ratings, contribution, and roster status |
| `analyze_situational_split`, `decompose_metric_change` | Catalog surface; selected NBA diagnostic cuts are not yet executed                        |
|             `compare_possession_outcomes`              | Catalog surface pending validated normalized possession outcomes                          |
|                  `query_play_by_play`                  | Catalog surface                                                                           |

Aggregate lineup releases support full regular-season or playoff scopes. Arbitrary date-bounded lineup segments require possession-level lineup data and fail explicitly
rather than silently applying full-season units. Box-score metric changes include a descriptive 95% game-level interval when each window contains at least two games.

### NBA evidence and enrichment

NBA reports apply the shared two-window selector to basketball events. Candidate scoring and relevance are domain-aware, allowing the selector to distinguish typical events,
metric-relevant examples, support for the observed change, and counterexamples without treating every made basket as support or every empty scoring field as a contradiction.
Evidence includes period, clock, score, event type, team/player context, shot result/value/distance/coordinates, and possession number when the source supplies them.

The basketball evidence view draws a half-court marker only when coordinates exist. It shows lineup cards only when on-court players are available; otherwise it falls back to
a textual event or possession timeline without inventing missing data.

The optional sync catalog includes every published high-level SportsDataverse NBA release loader: ESPN and NBA Stats schedules, box scores, shots, standings, officials,
coaches, game logs, season statistics, rosters, game rosters, draft results, identity data, player impact, play-by-play, and lineups. NBA Stats season and game rosters cover
1997 onward in the reviewed release snapshot; ESPN game rosters cover 2002 onward, and the separate ESPN season-roster release begins in 2025. Exact published seasons are
returned by `GET /api/sports/nba/options`, so the UI disables packages that do not cover the selected seasons.

SportsDataverse 0.0.75 also exposes V3 play-by-play, lineup, and possession loader functions, but their bulk release tags are not currently published. The connector preserves
those dataset identifiers for registered local or live-derived files without presenting them as downloadable packages.

Transport readiness is exposed in sport capabilities when `curl_cffi` is installed. The development `test` extra currently installs it; there is not yet a dedicated `nba-live`
dependency group. Current investigations use synced bulk data and do not make live NBA Stats calls, so this capability is reserved for future fallback enrichment.

## Soccer

Supported competitions: Premier League, MLS, La Liga, Bundesliga, Serie A,
Ligue 1, NWSL and UEFA Champions League. Select competition before season and
subject; competition identities isolate downloaded data.

For example, sync a competition with `uv run sports-analyst data sync soccer --competition eng.1 --season 2025`. For European leagues, the season number
is its ending year (2025 means 2024–25); MLS and NWSL use the calendar year. Selected-player assist game logs are requested and cached only if that metric is used and ESPN
provides the log for both windows.

Champions League uses `uefa.champions` and ending-year season labels (2027 means 2026–27). The existing match, player and xG analysis paths apply, subject to recorded
coverage. Evidence retains recorded stage and match notes, including shootout tallies where supplied. Comparisons are match-level, not aggregate-tie outcomes: extra-time goals
count, shootout tallies do not, and tied match scores remain draws. Points per match includes only recorded league/group-phase matches. Use date windows to narrow tournament
context; dedicated stage filters and two-legged tie analysis are not yet included.

**Team Match Statistics** also fetches ESPN Core expected-goals statistics through SportsDataverse in the same sync. Team analysis supports xG, xG against, xG difference,
non-penalty xG, and goals minus xG per match. Player scoring analysis supports recorded xG, non-penalty xG, and goals minus xG; only the selected player's match statistics are
fetched and cached when requested. Match evidence also displays each team's recorded xG. Sync Team Match Statistics (and lineups for players) before selecting these metrics.
Existing xG snapshots remain compatible; xG coverage is tracked independently internally and shown alongside the bundled match statistics.
Missing values are excluded, never replaced with zero, and comparisons report their qualifying-match coverage. Both windows need recorded values.
Historical coverage is not guaranteed; selectable metrics require recorded values in both windows. Source samples are documented in the [research verification guide](research-workflow.md#verification).
These are match statistics, not shot-location data or tracking replay.
See the [SportsDataverse Core statistics documentation](https://js.sportsdataverse.org/docs/soccer/reference/core#espnsoccereventcompetitorstatistics).

Soccer also offers **Published season** metrics in Customize metrics for full-season comparisons: team/player goals, assists, shots, shots on target, passes,
accurate passes, tackles, interceptions and appearances, plus player minutes. These Core season statistics are fetched and cached only for the selected subject.
The connector verifies season/subject references, uses combined totals without also adding their component stages, and requires verified match stages when summing
disjoint tournament phases. Missing partitions or fields are not treated as zero. Published totals remain distinct from locally reconstructed match totals and
cannot be used for date-range comparisons or inferred match events. Season xG/non-penalty xG metrics are offered only where cached season statistics record those fields;
historical team/player season endpoint samples also lacked xG. In-season snapshots are refreshed when requested.

## College football: FBS and FCS

The College Football tab discovers teams by **browse season → subdivision → conference/independents → school**.
Conference membership is season-specific and only organizes selection: team analysis includes recorded nonconference and cross-subdivision games.
Directories load on demand; selecting a conference does not download its rosters or game statistics. Player searches are limited to the chosen school/roster season,
with a maximum of 25 matches. Selecting a player verifies their historical seasons through ESPN's statistics log.

Run an investigation to prepare only the selected subject's missing game summaries and statistics. Team results and offensive box-score comparisons are supported,
as are quarterback, rushing and receiving player metrics. Player investigations follow ESPN athlete IDs and season game logs across transfers rather than matching names.
Rates use summed numerators and denominators. Missing sections and incomplete samples are shown as coverage gaps, never assumed to be zero.
Historical data is reused; current-season directories and snapshots refresh on bounded cache intervals. No national CFB season play-by-play or roster download is required.

For roster fallback, source availability, current-season refresh and shared
caches, see [data management](data-downloads.md). Optional NCAA/CFBD matching,
model compatibility and activation settings are maintained in
[CFB sources](cfb-source-terms.md).

CFB investigations prepare cached recorded plays for the endpoint windows before evidence selection. The shared diversity selector chooses metric-relevant typical,
supporting and counterexample plays from covered games; player examples require structured athlete-role IDs. Penalty/no-play rows are excluded from the evidence pool.
Box-score aggregates keep their own game/attempt denominators; play examples do not replace those totals or establish causality. Selected play IDs, selection reasons,
narrative formation labels and per-play personnel-source status are available to synthesis, follow-ups and exports. The tablet opens on the cited play and keeps
full-game browsing available as secondary context. Missing play coverage falls back to explicitly labeled game context. All marker positions remain illustrative;
formation labels and personnel endpoint entries do not establish tracking, routes, defensive assignments or a verified full on-field lineup.

The data manager supports explicit selected-school downloads; the conference selector also provides an explicit conference download for the selected sync seasons.
Scoped snapshots coexist in the catalog using team/player partition identities, while game summaries are shared across schools. Cloud replicas coordinate source requests
through durable leases; desktop processes use local leases. Clearing College Football data clears its source cache and snapshots, not saved investigations.

Game evidence shows recorded opponents, score, offensive statistics and scoring events. Opening CFB evidence automatically loads the selected game's recorded plays
through bounded, cached ESPN play requests. A searchable selector and previous/next controls open the college-football field tablet. Start/end yard positions,
down/distance, recorded scores and involved athlete IDs come from the source. School colors and provided home logos brand the field and markers.
The feed's participants are play actors, not a complete 22-player lineup; marker locations are explicitly illustrative. It does not supply actual formations,
routes, coverage assignments or tracking coordinates. Names resolve by athlete ID from that game's box score, without unrelated roster or per-athlete fan-out.
Older saved evidence without the new context can load recorded details while keeping its saved modeled values.
Enriched investigations also show offensive EPA/play, qualifying plays and game counts for the prepared comparison-window sample—not a national/conference ranking.
Optional advanced metrics trigger SportsDataverse's per-game processing pipeline against the cached summary, joined to bounded ESPN play/participant requests.
The **Enriched Plays** package can also be downloaded explicitly. Basic investigations do not run this heavier pipeline.

Supported modeled comparisons include offensive/passing/rushing EPA per qualifying scrimmage play, EPA-positive play rate, and spread-free offensive WPA.
Completion over expected (CPOE), expected pass rate and pass rate over expected are available when the provider returns finite values in both windows.
CPOE and pass-over-expected are percentage-point differences: `100*(observed indicator - modeled probability)`, averaged over qualifying plays.
Passing, rushing and receiving player EPA/WPA require structured ESPN athlete IDs on the corresponding plays; regex-extracted names and provider name-only ID matches
are never used for these comparisons. Receiver values describe attributed targets, including incompletions, not catches alone. WPA sums indicate game-state leverage,
not isolated individual contribution or the team's total change in win probability. EPA-positive success is defined as EPA > 0, not a yards-to-go success rule.

The shared enrichment cache retains the provider pipeline and advanced box outputs, package version, raw-summary checksum, processed/source play counts and identity policy.
Only normalized, explicitly defined metrics are offered for analysis. Partial sequences are labeled and retried on bounded cache intervals; missing plays remain missing.
Both comparison windows must use the same provider version. Model outputs are not independently calibrated here for FBS/FCS parity or historical eras.
Fourth-down/two-point decision surfaces remain disabled until verified market inputs and their definitions are integrated. Other pipeline columns are retained
in the provider output but are not automatically offered as validated comparison metrics. Opponent-adjusted ratings, recruiting projections, polls, betting analysis and
predictive
utilities need their own coverage/provenance and analytical contracts; their presence in the package does not make them interchangeable with observed match statistics.

App-wide preparation uses automatic coverage-driven preparation over persistent scoped caches, with a source-specific acquisition strategy.
Use per-game/team loading for CFB and soccer where supported; retain efficient season/package downloads for NFL/NBA bulk-only sources. Do not download a national file
and present post-download filtering as reduced network traffic. Keep explicit downloads and clearing available, historical cache reuse, current-season refresh,
bounded worker progress and missing-data messages. See [data preparation](data-downloads.md) for acquisition scope and performance.

CLI example: `uv run sports-analyst data sync cfb --season 2025 --team 333 --team 52`. Use `data list cfb` to inspect scoped snapshots.

## Football game browsing

NFL representative-play tablets also provide a recorded-game browser: search, previous/next, and return to the cited play. Browsing reads only that game's rows
from the synced season, without applying the investigation's team, player or situation filters. Opponent, special-teams and missing-EPA plays remain visible.
Available participation, charting and identity data enrich the same schematic. Browsing does not modify report evidence; a changed snapshot is labeled, and
the original cited play remains available when full-game data has been cleared or cannot load. Local installations and durable-storage deployments use the same path.

## Football kick and return diagrams

The shared NFL/CFB tablet renders field goals, extra points, punts and kickoffs as
kick/return diagrams. It does not substitute a normal offensive formation or infer
a full coverage/blocking unit. Recorded specialists are identified where supplied;
unnamed markers remain generic. Lateral positions and curved paths are illustrative.

NFL game evidence preserves the kick type, specialist names, kick and return
distances, result, and relevant touchback/fair-catch/block flags. nflverse kickoff
possession refers to the receiving team: its start yardline is converted to the
kicking team's direction before drawing. Other scrimmage kicks retain their
recorded possession orientation. Goal-kick distances locate the illustrative kick
origin relative to the back-of-end-zone posts, rather than treating the distance
as line-of-scrimmage yardage. Punter depth is illustrative; punt distance remains
measured from scrimmage.

CFB uses recorded ESPN start/end context and specialist roles. Available
SportsDataverse `yds_punted`, `yds_punt_return`, `yds_fg`, `yds_kickoff` and
`yds_kickoff_return` values are retained as provider-derived narrative context.
Explicit narrative distances also support older cached plays and saved reports.
Net play yardage never substitutes for kick or return distance. The render cache
version is incremented to refresh previously normalized games without changing
saved EPA/WPA or analysis measurements.

Kick flight travels toward the receiving goal; recorded returns travel back toward
the kicking goal. Touchbacks, fair catches, downed kicks and out-of-bounds kicks
do not get return arrows. A touchback placement marker requires an explicit
recorded end spot or a team-verified narrative placement; no rule-dependent spot
is guessed from sport or season. Blocked, nullified, or unlocated attempts do not
receive invented completed flight paths. Missed field goals show the recorded
outcome and reference posts without inventing the lateral miss or landing point.

Tablets show an interactive loading preview while their component or recorded
play details load. The preview does not change evidence. Loading failures offer
a retry; existing cited NFL plays remain usable while full-game context loads.

## Evidence, provenance, and exports

The sport plugins return sport-correct findings, charts, representative evidence, tool records, and source manifests. Reports and export bundles retain dataset hashes, evidence
selection metadata, and source provenance. Football evidence keeps the field visualization; basketball evidence uses the basketball renderer described above.

Follow-up questions reuse the saved investigation context. History is scoped by sport in the workbench.

Investigation progress is streamed over server-sent events. If that stream disconnects, the frontend checks the persisted status. A completed result is rendered only after
both its full bundle and conversation thread pass completeness checks; transient persistence/read races are retried with bounded backoff.

The desktop uses an AppData-backed SQLite queue and a managed sibling worker;
command-line development retains in-process execution. See [environment settings](environment.md).
Both investigation and sync streams have frontend status recovery.
Workers renew leases, retry temporary failures, and reuse already-published investigation results after a crash.
Worker execution is at least once: a crash before a result is saved can repeat a model call.
Desktop progress and retry state survive restarts in `jobs.sqlite3`; datasets, investigations, exports, and the DuckDB catalog remain separate files in the same per-user data
directory.

## Adding a sport or analytical tool

A new sport should implement the shared connector and plugin contracts, register its datasets and capabilities, normalize source schemas at the connector boundary, and keep
all storage keys sport-scoped. A new tool should declare its inputs and data requirements, return deterministic evidence, and degrade explicitly when required fields or
datasets are unavailable.


## CLI reference

The web application is the primary interface. The CLI supports sport-specific data sync, manifest inspection, investigation inspection/export, and NFL full-season `ask` requests.
NBA investigation authoring currently uses the web application or HTTP API.

```powershell
# Sync play-by-play only
uv run sports-analyst data sync nfl --season 2024 --season 2025

# Sync selected supplemental packages
uv run sports-analyst data sync nfl `
  --season 2024 --season 2025 `
  --dataset play_by_play `
  --dataset rosters `
  --dataset injuries `
  --dataset snap_counts `
  --dataset participation

# Sync the default bulk NBA packages for two seasons
uv run sports-analyst data sync nba --season 2025 --season 2026

# Add optional NBA shot and lineup packages where supported
uv run sports-analyst data sync nba --season 2025 --season 2026 `
  --dataset play_by_play --dataset schedules `
  --dataset team_boxscores --dataset player_boxscores `
  --dataset shots --dataset lineups

# Inspect local manifests
uv run sports-analyst data list --sport nba

# Run full-season analyses
uv run sports-analyst ask "Why did Kansas City's passing efficiency change?" `
  --team KC --compare 2024:2025 --domain passing

uv run sports-analyst ask "How did Chicago's rushing performance change?" `
  --team CHI --compare 2024:2025 --domain rushing

# Inspect and export saved work
uv run sports-analyst investigate show <investigation-id>
uv run sports-analyst investigate export <investigation-id> --format html

# Runtime and evaluation metadata
uv run sports-analyst capabilities
uv run sports-analyst providers check
uv run sports-analyst eval run
```

Run `uv run sports-analyst --help` or append `--help` to a subcommand for its current options.

## HTTP API

FastAPI exposes:

|      Area      | Endpoints                                                                                                                                                                                |
|:--------------:|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|    Runtime     | `GET /api/capabilities`, `GET /api/sports`                                                                                                                                               |
|      Data      | `GET /api/datasets?sport={sport}`, `POST /api/datasets/{sport}/sync`, `POST /api/datasets/{sport}/sync-stream`, `GET /api/dataset-jobs/{id}/status`, `GET /api/dataset-jobs/{id}/events` |
| Sport catalog  | `GET /api/sports/{sport}/options`, `GET /api/sports/{sport}/tools`, `GET /api/sports/{sport}/metrics/{metric}`, `GET /api/sports/{sport}/players`                                        |
| Investigations | `POST /api/investigations`, `GET /api/investigations?sport={sport}`, `GET/DELETE /api/investigations/{id}`, `GET /api/investigations/{id}/events`, `GET /api/investigations/{id}/status` |
|  Conversation  | `GET /api/investigations/{id}/thread`, `POST /api/investigations/{id}/follow-ups`                                                                                                        |
|    Evidence    | `GET /api/investigations/{id}/evidence/{evidence_id}`, `POST /api/investigations/{id}/evidence/batch`                                                                                    |
|    Reports     | `GET /api/investigations/{id}/export?format=html`, `GET /api/investigations/{id}/export?format=markdown`                                                                                 |

Dataset sync and investigation progress use server-sent events or status polling, selected by runtime capabilities. The frontend recovers
interrupted work through the status endpoint and validates the complete
bundle and thread before rendering them. History responses are compact summaries; complete bundles, threads, and evidence are loaded on demand.

Interactive OpenAPI documentation is available at [http://127.0.0.1:8767/docs](http://127.0.0.1:8767/docs) while the API is running.
