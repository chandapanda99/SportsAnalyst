# Sports Tool Guide

This guide describes the analytical tools and capabilities currently exposed by the NFL and NBA plugins. It distinguishes implemented investigation behavior from catalog
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

## Shared investigation contract

Every investigation identifies:

- a `sport` (`nfl` or `nba`);
- a subject with a stable `id`; both NFL and NBA accept `team` or `player` subjects;
- two analysis windows;
- a plugin-defined domain and selected metrics;
- optional diagnostic cuts and a natural-language question.

Legacy NFL payloads remain valid: a missing sport defaults to `nfl`, a missing explicit subject is inferred from `scope.team`, and legacy `baseline_season` /
`comparison_season` values become complete-season windows. Current NFL windows use the inclusive `weeks` pair directly; NBA windows add a normalized `segment` value.

Datasets, manifests, cached files, and SQL views are partitioned by sport, dataset, and season. Internal play-by-play queries always include the sport boundary, so an NBA
investigation cannot read NFL data and vice versa.

### Shared representative-evidence selector

Both plugins use the deterministic, versioned `diverse-v1` selector. Candidates from the baseline and comparison windows are considered together, then up to four distinct
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

| Domain  |        Metric         | Definition                                                  |
|:-------:|:---------------------:|-------------------------------------------------------------|
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

|                       Capability                        | Status                                                                                    |
|:-------------------------------------------------------:|-------------------------------------------------------------------------------------------|
|                 `compare_time_windows`                  | Implemented for team and player box-score metrics                                         |
|                 `analyze_season_trends`                 | Implemented as a multi-season chart plus the two selected-window aggregates               |
|               Traded-player stint filter                | Implemented                                                                               |
|       `find_representative_possessions` behavior        | Implemented from both windows of synced play-by-play as part of the investigation         |
|                    Lineup comparison                    | Implemented when compatible lineup seasons are synced for both windows                    |
|   Local/live-derived V3 possession/lineup enrichment    | Implemented when matching rows are registered; no V3 bulk release is currently advertised |
|       `analyze_game_trends`, `rank_game_outliers`       | Executed for box-score analyses, with game variability and comparison-window extremes     |
| `benchmark_against_league`                              | Executed for team analyses when the comparison release contains league rows                |
| `adjust_for_opponents`                                  | Executed as descriptive schedule context when opponent identities are available            |
| `compare_shot_profiles`                                 | Executed for shooting analyses from recorded play-by-play shot value/distance              |
| `compare_player_usage`                                  | Executed for player analyses to separate minutes/involvement from efficiency                |
| `analyze_lineup_performance`                            | Executed with named units, minutes, possessions, ratings, contribution, and roster status  |
| `analyze_situational_split`, `decompose_metric_change`  | Catalog surface; selected NBA diagnostic cuts are not yet executed                         |
| `compare_possession_outcomes`                           | Catalog surface pending validated normalized possession outcomes                           |
|                  `query_play_by_play`                   | Catalog surface                                                                           |

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

## Evidence, provenance, and exports

Both plugins return sport-correct findings, charts, representative evidence, tool records, and source manifests. Reports and export bundles retain dataset hashes, evidence
selection metadata, and source provenance. Football evidence keeps the field visualization; basketball evidence uses the basketball renderer described above.

Follow-up questions reuse the saved investigation context. History can be filtered by NFL, NBA, or all sports.

Investigation progress is streamed over server-sent events. If that stream disconnects, the frontend checks the persisted status. A completed result is rendered only after
both its full bundle and conversation thread pass completeness checks; transient persistence/read races are retried with bounded backoff.

## Adding a sport or analytical tool

A new sport should implement the shared connector and plugin contracts, register its datasets and capabilities, normalize source schemas at the connector boundary, and keep
all storage keys sport-scoped. A new tool should declare its inputs and data requirements, return deterministic evidence, and degrade explicitly when required fields or
datasets are unavailable.
