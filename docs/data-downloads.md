# Download performance and diagnostics

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
