# Shared dataset availability safeguard

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

No new APIs, source subscriptions, provider packages or settings are required.
The separate concurrency bug in fatal-error progress attribution is deliberately
not changed here; this safeguard does not claim to fix it.
