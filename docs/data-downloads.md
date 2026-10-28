# Data preparation, availability and diagnostics

NFL, NBA, soccer and college-football investigations check their selected data scope before analysis and prepare missing dependencies in the investigation worker.
Progress remains attached to the investigation; a separate manual sync is no longer required when a valid subject and preparable periods can be selected.
The UI distinguishes **locally available** seasons from **preparable** source seasons. A preparable metric is not a promise that both windows contain usable values:
the deterministic analysis still verifies attribution, required fields and qualifying samples. Player selection requires a discoverable identity; this flow does not
invent player history, historical roster membership or missing source statistics. Explicit library downloads remain available for offline use and bulk research.

NFL/NBA retain their published bulk package formats. Ordinary preparation fetches core/metric dependencies rather than every optional package.
Successful historical snapshots are reused; incomplete acquisition is retried. Automatic current-season preparation reuses snapshots acquired within one hour,
then refreshes needed packages. Explicit sync retains its existing current-season refresh behavior. Preparation leases coalesce desktop workers on shared local storage
and cloud replicas when durable conditional-write persistence is configured. Without durable persistence, cloud caches/coordination remain instance-local.

Soccer team investigations prepare **team/competition/season partitions**, fetching summaries only for that team's fixtures, including its opponents.
An existing complete competition snapshot can be projected locally without source downloads or overwriting that snapshot; original acquisition time and provenance
are preserved. Fixtures still use the provider's competition schedule discovery; this is scoped match-detail acquisition, not a claim of team-filtered network
scoreboard downloads. Successful raw summaries are shared locally and, when configured, durably across preparations. Simultaneous current-season summary refreshes
may reuse a five-second hot cache. Results-only preparation does not request xG; explicit Team Match Statistics downloads still bundle xG as before.
Soccer player investigations retain competition-wide preparation to avoid excluding transfer appearances. Empty libraries can use a cached lightweight team directory;
historical clubs not in that current directory can still be discovered through explicit season fixture downloads. Library package badges describe full competition
downloads, not a small team snapshot. Clearing a competition removes its scoped snapshots and raw caches without deleting saved investigations.

## Availability and refresh

All four sport connectors use `datasets/availability.py` for explicit source
absence and/or completed-game filtering and last-good-data retention. The shared
sync runtime publishes coverage-gap completion messages and retries unavailable
historical packages rather than treating their manifests as installed successes.
These metadata and files use the same local/durable persistence paths.

- HTTP 404/410, explicit provider season-not-found signals and successfully
  fetched empty package results are availability gaps. Unknown exceptions are
  not classified by their text. Permission, rate-limit, server, timeout, format
  and storage failures are not turned into successful empty downloads.
- NFL/NBA continue other selected packages and register unavailable/partial
  manifests. Soccer retains league/team-specific gaps and only requests match
  details/statistics for completed matches. CFB uses the same completed-game
  filter and retains its detailed completed-game coverage counts.
- A failed unavailable refresh retains previously downloaded rows with a partial
  status and explicit message. An absent package gets a separate empty placeholder
  marked `source_unavailable`, not an available zero-statistics dataset.
- Missing optional data need not prevent analysis of unrelated recorded metrics.
  Missing required data fails preparation explicitly. A fetched soccer match with
  an explicitly empty event list remains a verified zero-event match; an unfetched
  match does not become one.
- Available historical packages are reused. Unavailable records are rechecked on
  a later sync. Current-season refresh policy is unchanged. CFB's existing short
  retry/cache windows for availability checks remain in effect.
- Successful checkpoints are published to the durable catalog even when another
  package has a genuine failure. Source gaps are listed in the completion message.

## Download performance

`DATASET_SYNC_CONCURRENCY=4` is a reasonable starting point for overlapping
independent requests. Restart the running backend/desktop worker after changing
the environment. This is a per-process limit, not a deployment-wide rate limit;
multiple cloud workers can still put more load on the provider. Reduce it if
rate limits or memory pressure increase. NFL/NBA retain bulk dataset downloads.

CFB summary, historical-athlete-reference, and recorded-play preparation use
bounded work queues: a finished request immediately makes room for the next
item instead of waiting for a batch's slowest request. Nested CFB game/identity
requests share the source instance's HTTP semaphore. Team/season preparation
remains ordered to keep conference progress and memory predictable; expensive
EP/WP modeling remains sequential rather than multiplying CPU/model memory.

The shared CFB/soccer source cache checks local disk before durable storage and
promotes durable hits locally. Source acquisition timestamps and each caller's
TTL are preserved; reading a cache never renews freshness. Explicit sync and
preparation entry points still invalidate caches after a library reset. Direct
source reads check cross-instance reset generations at most five seconds apart;
old-generation local and durable objects cannot be reused after that check.
Transient request failures are not cached as empty successes.

CFB normalized play results are shared by game, season, summary hash, identity
adapter version, and installed provider version. Current-season results expire
after an hour; historical results use the existing historical source TTL.
Incomplete participant identities, missing team game rosters, and failed optional rendering enrichment are
not persisted as successful normalized games, so later requests can recover.
Analysis-critical attribution is not deferred or omitted. Increment the
normalized-cache version when changing the normalization contract.

Recorded CFB play downloads use only games explicitly marked completed, not
fixture dates or the presence of a schedule entry. Coverage records
`scheduled_matches`, `skipped_uncompleted_matches`, and
`missing_completed_matches`; the existing expected/fetched counters refer only
to eligible completed games. Missing completed-game plays remain partial and
retryable, even when every completed game is missing. Future-only selections
save the schedule and an empty play snapshot with a “not expected yet” message,
zero expected games, and no play requests or error tracebacks. Optional modeled
play preparation also skips such selections without loading the model pipeline.

CFB sync saves each dataset and its durable metadata immediately, but publishes
the combined catalog once on completion (or on failure with partial successes).
Reused registered snapshots are not uploaded again. Snapshot row/column ordering
is deterministic, so request completion order does not change checksums.
Unchanged bytes also avoid another upload when freshness metadata advances.
Existing per-resource
leases, historical reuse, partial retry, and current-season refresh remain in
place. The dedicated cloud sync runtime also initializes soccer's shared cache.

## Measuring results

Worker logs include `dataset_stage` entries with stage, status, duration in
milliseconds, and safe sport/season/partition context. Stages distinguish source
requests, durable cache reads/writes, roster resolution, game summaries,
normalization, dataset saving, and catalog publication. Cache tiers are logged
at DEBUG. These logs contain no credentials or full source response bodies.

Compare the same selected scope under a fresh cache, a warm cache, an interrupted
retry, and a current-season refresh in both desktop and cloud environments.
Record wall time, stage durations, source request count, throttling/timeouts, and
peak worker memory. Parallel stage durations overlap: do not sum them as total
elapsed time. Do not assume a particular speedup from the concurrency setting.

## Packages and local storage

Data is downloaded through `nflreadpy` (NFL) or SportsDataverse (NBA), normalized to local Polars/Parquet data, and registered in a DuckDB catalog. The repository does not
contain or redistribute sports datasets.

### NFL packages

|        Category         | Packages                                                                               | Used for                                                                                                                     |
|:-----------------------:|----------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------|
|        Required         | `play_by_play`                                                                         | Core metrics, trends, splits, outliers, benchmarks, representative plays, and schematics                                     |
| Team and player context | `player_stats`, `rosters`, `weekly_rosters`, `injuries`, `snap_counts`, `depth_charts` | Usage, availability, roster composition, and continuity                                                                      |
|      Play context       | `participation`, `ftn_charting`, `schedules`                                           | Recorded participants, personnel, pressure, routes, coverage, motion, play action, RPO, screens, opponents, and game context |
|     Next Gen Stats      | `nextgen_passing`, `nextgen_receiving`, `nextgen_rushing`                              | Passing, receiving, and rushing context published through nflverse                                                           |
| PFR advanced statistics | `pfr_passing`, `pfr_rushing`, `pfr_receiving`, `pfr_defense`                           | Weekly advanced player and defensive context                                                                                 |
|    Shared references    | `players`, `teams`                                                                     | Cross-source identity resolution and canonical team metadata                                                                 |

Package availability varies by season. The UI displays each package's first supported season, disables invalid combinations, and reports local coverage for the selected years.
Shared `players` and `teams` references are stored once rather than once per season.

Supplemental data is optional. The service selectively loads only packages relevant to the question and domain. When a useful package has not been synced, the investigation
continues with available evidence and records a capability caveat.

### NBA packages and availability

NBA seasons are stored by ending year: `2026` is displayed as `2025–26`. Core ESPN-backed releases begin in 2002. The default NBA sync contains `play_by_play`, `schedules`,
`team_boxscores`, and `player_boxscores`. The sync catalog covers every published high-level NBA loader in SportsDataverse 0.0.75, including ESPN and NBA Stats schedules, box
scores, shots, standings, officials, coaches, game logs, season statistics, rosters, game rosters, draft results, identities, impact, play-by-play, and five-player lineups.
NBA Stats season and game rosters are available from 1997, while the separate ESPN season-roster release begins in 2025. Named segments are offered only when schedule rows and
reviewed boundaries resolve qualifying games. V3 play-by-play, lineup, and possession loaders remain local/live-only compatibility sources because no corresponding bulk
release tags are currently published; they are not shown as downloadable packages.

SportsDataverse is constrained to the pre-1.0 `>=0.0.75,<0.1` compatibility line (the current lockfile resolves 0.0.75). Loader calls are isolated inside
`SportsDataverseNBAConnector`, where schemas, identifiers, season conventions, checksums, caching, and package availability are normalized before the analysis plugin sees
them.

### Local storage and provenance

By default, files are stored in the platform-specific user data directory returned by `platformdirs`:

```text
open-sports-analyst/
├── catalog.duckdb
├── raw/nflverse/*.parquet
├── raw/nba/*.parquet
└── investigations/<investigation-id>/
```

Set `DATA_DIR` in `.env` to use a different root directory.

The data manager's **Clear downloaded data** action removes all seasons for the active sport (only the selected competition for soccer), including source caches. Saved
investigations
and settings are retained; dataset-backed tools need a fresh sync afterward. Deletion is
permanent unless you have a backup or object-storage versioning enabled.

Optionally configure `SPORTS_ANALYST_DATA_ADMIN_TOKEN` to protect dataset deletion.
The UI requests it only when clearing data and does not save it. This is not general
authentication; keep the development server private. Wait for queued/running work to
finish before clearing data; detected active jobs block deletion.

Every dataset manifest records its sport, source, season, acquisition time, schema, package version, local SHA-256, size, license, and attribution. Catalog lookups, SQL views,
history, and caches are partitioned by sport so an NBA request cannot resolve an NFL manifest. Investigation bundles also retain tool versions, parameters, execution timing,
result hashes, evidence identifiers, charts, and reports.

Framework code is MIT-licensed. Synced datasets and derived outputs retain the attribution and terms recorded in their source manifests.
