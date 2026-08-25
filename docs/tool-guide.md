# NFL Tool Guide

This guide describes the deterministic analytical capabilities registered by the NFL plugin. These tools calculate and validate evidence; the language model plans an
investigation and explains the resulting evidence but does not execute Python or invent measurements.

## Using the catalog

The registered catalog is available from:

```http
GET /api/sports/nfl/tools
```

Each catalog entry includes a stable tool name, description, analytics version, and—where defined—a JSON input schema. Structured UI options and field availability come from:

```http
GET /api/sports/nfl/options
```

Metric definitions are available from `GET /api/sports/nfl/metrics/{metric}`. Player search is available from `GET /api/sports/nfl/players?query={text}`.

There is intentionally no generic public endpoint that executes an arbitrary tool call. An investigation validates its typed request, creates an `AnalysisPlan`, and invokes
registered implementations inside the NFL plugin. Constrained SQL is available internally through the application service for combinations not covered by a predefined
operation.

## Shared analytical rules

- Each investigation selects a play population: quarterback dropbacks, qualifying rushing attempts, or overall offensive plays.
- Comparison windows require at least 30 qualifying plays each.
- Situational subgroups require at least 10 qualifying plays in both windows.
- Full-season ranges analyze every synced season from the selected start through end season.
- Formation and personnel analysis is omitted when fields are missing or materially incomplete.
- Every result records its tool version, parameters, input dataset manifests, runtime, result hash, and stable evidence identifier.
- Results are descriptive and observational. They do not establish causality.

Passing metrics are EPA/dropback, success rate, CPOE, explosive-pass rate, yards/play, sack rate, interception rate, air yards/attempt, and YAC/completion. Rushing metrics are
EPA/rush, rush success rate, yards/rush, explosive-run rate, stuff rate, and rushing first-down rate. Overall-offense metrics are EPA/play, overall success rate, overall
yards/play, and turnover rate. Supported diagnostic cuts are down, distance, field zone, score state, shotgun, no huddle, personnel, and formation when the required source
fields are available.

## Discovery and validation

|           Tool            | Purpose                                                                                                                                          | Data requirement                             |
|:-------------------------:|--------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------|
|  `get_analysis_options`   | Returns valid teams, synced and syncable seasons, metrics, defaults, split dimensions, comparison modes, and season-specific field availability. | Dataset manifests; no play rows are scanned. |
| `validate_analysis_scope` | Validates team resolution, seasons, windows, metric and split names, required fields, and minimum samples before analysis.                       | Play-by-play for every requested season.     |
|     `explain_metric`      | Returns the metric definition, formula, qualifying-play rule, interpretation guidance, preferred direction when meaningful, and limitations.     | No dataset required.                         |

## Core comparison and diagnosis

|            Tool             | Purpose                                                                 | Main inputs                                                                        | Evidence produced                                                                                                        |
|:---------------------------:|-------------------------------------------------------------------------|------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------|
|   `compare_time_windows`    | Measures selected metrics between two season/week windows.              | Team, analysis domain, baseline window, comparison window, season type, metrics.   | Baseline value, comparison value, difference, sample size, and game-bootstrap confidence interval where available.       |
|   `analyze_season_trends`   | Measures each season in an inclusive full-season range.                 | Team, included seasons, metrics.                                                   | One measurement and confidence interval per season and metric.                                                           |
|   `analyze_weekly_trends`   | Determines whether a change is sustained or concentrated.               | Team, one or two windows, metric; three-week moving average by default.            | Weekly values, bootstrap intervals, three-week moving averages, and sustained/mixed/outlier-concentrated classification. |
|    `rank_game_outliers`     | Finds comparison-window games farthest from the baseline expectation.   | Team, comparison window, metric, result limit.                                     | Ranked game-level differences and qualifying-play samples.                                                               |
| `benchmark_against_league`  | Places team performance in league context for each window.              | Team, windows, metrics.                                                            | NFL percentile, NFL rank, AFC/NFC rank, and distance from league average.                                                |
| `analyze_situational_split` | Compares performance within registered football situations.             | Metric, split dimensions, minimum subgroup sample.                                 | Baseline, comparison, and change for every qualifying subgroup.                                                          |
| `find_representative_plays` | Selects source plays that support or challenge the aggregate diagnosis. | Team, window, supporting and counterexample limits, optional minimum absolute EPA. | Game ID, play ID, description, EPA, support/counterexample role, and source manifest.                                    |

The current typed investigation scope supports full seasons, custom week ranges, and before/after-week comparisons. Rolling-N-game and arbitrary-date windows are planned
extensions rather than current scope options.

## Decomposition and context

|           Tool            | Purpose                                                                                     | Data requirement                                                                                                  |
|:-------------------------:|---------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------|
| `decompose_metric_change` | Separates changes associated with situational mix from within-group performance changes.    | Play-by-play and selected split fields.                                                                           |
|  `adjust_for_opponents`   | Compares raw EPA with leave-one-game-out defensive baselines.                               | Play-by-play containing offense, defense, game ID, and EPA; opponent samples require at least 30 other dropbacks. |
|   `analyze_game_state`    | Analyzes performance while leading, tied, and trailing.                                     | Play-by-play with score differential.                                                                             |
|    `compare_play_mix`     | Measures changes in the frequency of selected situations, personnel, formations, and tempo. | Play-by-play and selected split fields.                                                                           |
| `identify_change_points`  | Finds descriptive week boundaries with the largest sustained shift.                         | Weekly play-by-play values for the selected metric.                                                               |

Decomposition results from overlapping dimensions must not be summed together. They are descriptive diagnostics, not causal attribution.

## Player, roster, and availability context

|                  Tool                   | Purpose                                                                                            | Primary dataset                                      |
|:---------------------------------------:|----------------------------------------------------------------------------------------------------|------------------------------------------------------|
|            `resolve_player`             | Resolves player names or identifiers and reports teams, positions, and seasons.                    | Rosters, player statistics, or play-by-play.         |
|       `build_player_week_dataset`       | Resolves identities and normalizes roster, injury, snap, and play-participant data by player-week. | Play-by-play; supplemental packages enrich the rows. |
|          `get_roster_context`           | Compares roster composition by position across windows.                                            | Rosters.                                             |
|     `analyze_starter_availability`      | Compares recorded injury and availability reports.                                                 | Injuries.                                            |
| `summarize_injured_or_inactive_players` | Ranks players most frequently listed unavailable.                                                  | Injuries.                                            |
|         `compare_player_usage`          | Compares target, carry, opportunity, snap-normalized usage, and EPA per opportunity.               | Normalized player-week layer.                        |
|  `analyze_position_group_availability`  | Estimates recorded availability by position, weighted by median healthy-week snaps when possible.  | Rosters, injuries, and snap counts.                  |
|       `analyze_lineup_continuity`       | Measures returning snap share and weighted snap-distribution similarity overall and by position.   | Snap counts and normalized player identities.        |
|      `decompose_lineup_continuity`      | Attributes comparison-window new-player snap share to position groups.                             | Snap counts and normalized player identities.        |
|       `analyze_qb_receiver_pairs`       | Compares quarterback-receiver volume and EPA per target.                                           | Play-by-play with passer and receiver fields.        |
|     `join_nextgen_passing_metrics`      | Compares supported Next Gen Stats passing measurements.                                            | Next Gen passing.                                    |
|    `join_nextgen_receiving_metrics`     | Compares separation, cushion, expected YAC, and YAC over expectation.                              | Next Gen receiving.                                  |
|     `join_nextgen_rushing_metrics`      | Compares rushing efficiency, box frequency, time to the line, and RYOE.                            | Next Gen rushing.                                    |
|      `join_participation_context`       | Adds recorded on-field players, personnel, pressure, routes, and coverage.                         | Participation plus play-by-play IDs.                 |
|       `join_depth_chart_context`        | Measures listed first-unit availability and returning-player continuity.                           | Depth charts and normalized player weeks.            |
|           `join_ftn_charting`           | Compares motion, play action, RPO, screen, pressure, and charted outcome rates.                    | FTN charting plus play-by-play IDs.                  |
|        `join_pfr_advanced_stats`        | Compares available advanced passing, rushing, receiving, and defensive measurements.               | Corresponding PFR advanced package.                  |
|         `join_schedule_context`         | Adds opponent, location, scoring-margin, and schedule context.                                     | Schedules.                                           |

The normalized layer prefers GSIS identifiers, maps PFR or source-specific identifiers through matching player names when possible, and falls back to a normalized name key. It
stores team, season, week, player identity, position group, roster and injury status, offensive/defensive/special-teams snaps, targets, carries, quarterback dropbacks,
opportunities, and participant EPA. Season-level roster membership is projected only across locally observed team weeks.

When participation is synced, continuity weights use recorded play-level appearances; otherwise they fall back to game-level snap counts. Returning snap share asks how much of
the comparison window's recorded participation belongs to players also observed in the baseline. Weighted Jaccard similarity additionally captures changes in how snaps were
distributed among returning and new players. Position-group turnover contributions describe where new-player snaps occurred; they do not measure replacement quality or
establish that turnover caused a performance change.

Weekly rosters supersede season-level roster projection for synced seasons. Depth charts provide listed role and rank but do not prove which player started a particular play.
Participation is available only for supported completed seasons and records lineup membership rather than player coordinates or movement.

Supplemental datasets are optional. If they are unavailable for both windows, the investigation skips the affected tools and records a capability caveat instead of fabricating
context.

## SQL and compatibility aliases

`query_play_by_play` represents constrained, read-only DuckDB SQL. SQL accepts one `SELECT`, `WITH`, or `EXPLAIN` statement and rejects mutation, extensions, file functions,
network functions, comments, and multiple statements. The current service helper applies an output-row limit and returns execution duration. Persisting SQL as an investigation
tool record and enforcing a hard query timeout remain required before SQL is exposed as a public execution endpoint.

The catalog retains these compatibility aliases for older plans:

- `compare_passing_efficiency` → `compare_time_windows`
- `decompose_situational_splits` → `decompose_metric_change`
- `rank_representative_plays` → `find_representative_plays`

New plans should use the canonical names.

## Evidence and provenance

Analytical tools return `AggregateEvidence` or `PlayEvidence`. Measured claims must cite these records. Each execution also creates a `ToolExecutionRecord` containing:

- Tool name and analytics version
- Validated parameters
- Start time and duration
- Dataset manifest identifiers
- Deterministic result hash
- Normalized SQL when the execution path supplies it

The application assigns and validates evidence IDs. Model-generated prose cannot create valid evidence records or select arbitrary identifiers outside the citation ledger.

## Adding a new tool

1. Add the deterministic implementation to the appropriate sport plugin.
2. Register a canonical `ToolDefinition` with a JSON input schema.
3. Add the tool to the plugin's typed planning rules only where it is useful.
4. Return versioned evidence and a `ToolExecutionRecord` with all source manifests.
5. Enforce field coverage, sample thresholds, deterministic ordering, and stable identifiers.
6. Add a high-level test covering formulas, provenance, unsupported inputs, and reproducibility.
7. Document required datasets, interpretation guidance, and limitations here.

Algorithms that are not implemented as registered, tested tools must be reported as unsupported. They must not be approximated through model-authored Python in the current
runtime.
