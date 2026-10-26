# CFB source integration

The source audit now validates team identity, learns **game-scoped** field-side
aliases from corroborated drives, and aligns plays through a bounded weighted
sequence crosswalk. Opt-in production adapters now use the same rules during
recorded-play preparation, advanced preparation and tablet reads. Secondary
sources remain disabled until the operator confirms permitted usage. See
[source review and settings](cfb-source-terms.md).

## Production integration

### Feature policy (`cfb-features-1`)

Conventional comparisons use the same ESPN definitions in both windows. Advanced
metrics use the same verified current model bundle. Neither feature requests
secondary context. Historical alternate-source samples must remain separately
scoped; they are not silently substituted into an existing comparison.

Secondary rendering context is requested only for selected report evidence or
when a game tablet is opened, and only for missing applicable fields or a known
semantic refinement. NCAA supplies the verified rendering fields. CFBD currently
has no verified additional rendering-field contract, so enabling it does **not**
download national assets during routine analysis/tablet use. Its acquisition is
limited to explicit `source_review` calls/audits until such a contract is verified.

Resolution version `cfb-resolved-2` replaces the blanket provider ranking with
per-field validity, definition and corroboration checks. Valid recorded primary
context is protected. Unknown/invalid placeholders may be replaced; a generic
parsed `Shotgun` label may be refined to corroborated `No Huddle-Shotgun` context,
but not an incompatible formation. This describes narrative context, not measured
alignment. Decisions, rejected observations, coverage and conflicts are retained
in provenance and exposed in the tablet. Core cited-play facts and modeled values
are never changed by rendering enrichment. The source catalog exposes the policy.

- NCAA discovery loads a small season schedule index, then fetches at most four
  candidate bundles for a selected game and requires one verified identity. No
  national roster or national play download is used for NCAA acquisition.
- CFBD-derived acquisition caches one bounded, checksum-verified release asset
  per season/content hash. It scans only the selected game's rows into memory.
  The opt-in bulk download is not part of default preparation.
- Both adapters use existing local/durable leases and caches. Raw payloads,
  extensions, source receipts and model fields are retained privately. Failures
  remain retryable rather than cached as empty successes. Current-season
  discovery refreshes; historical successful payloads are reused.
- Resolution supplements only approved formation/direction/depth/out-of-bounds
  fields under the feature policy above. Conflicts stay in field
  provenance and are shown in the tablet and report. All primary plays survive,
  including penalties, unsupported events and overtime.
- Primary snapshots carry `resolution_version`, `input_manifest_ids` and full
  input receipts. ESPN summary/plays and each acquired secondary payload receive
  isolated game/provider/version manifests. Inputs use content-addressed paths.
  Legacy primary channel/version defaults remain compatible with old records.
- Secondary raw EPA/WPA are **not** analysis inputs. Advanced values are
  recomputed using the installed SportsDataverse pipeline, keyed by the package,
  pipeline policy and SHA-256 of the EP, spread-free WP, CP and xpass artifacts.
  Advanced comparisons require a single identical model identity in both windows.
  Old advanced data lacking that identity must be re-prepared, not silently mixed.
- Existing analysis/evidence/follow-up paths consume the resolved primary rows.
  The tablet exposes source status, coverage, clock disagreements and conflicts.
  Clearing CFB data also removes provider caches and manifests.

## Matching contract

- Verify game, season/academic year, both teams, home/away and final scores.
  Missing NCAA ESPN team IDs can be resolved only through an exact ESPN school
  name/location plus the verified game, side and score. An explicitly conflicting
  ID is never overwritten by a name match. Player names are never identity joins.
- Verify drive identity using team, start/end period and clocks, play count,
  yardage, result and starting field position. Unknown/conflicting field aliases
  stay unresolved; no global abbreviation substitution table is inferred.
- Match possession, period, down, distance, starting field position, event family
  and gain. Compare scores, end position and drive whenever both feeds supply
  them. Only unique, order-preserving links across optimal alignments survive.
- Missing clocks require verified drive and score context. Conflicting clocks
  additionally require an agreeing end position. They remain explicit conflicts,
  not rewritten timestamps. Neither source establishes that the differing clock
  represents a particular timing convention.
- Exclude penalties/no-play rows and unsupported event families from linking;
  do not shift later plays by ordinal to compensate for administrative rows.
  Unknown periods, quarter-spanning drives and incomplete overtime remain gaps.
- At most 1,000 events per source/game and 25,000 candidate links are processed.
  The audit reports unmatched rows as unmatched—not as proof of missing plays.

## Repeat the audit

From the repository root:

```powershell
.venv\Scripts\python.exe -m sports_analyst.datasets.cfb_source_audit --output docs/audits/cfb-source-audit.json
```

Four live samples cover 2025 FBS, 2017 FCS, the 2024 Georgia–Georgia Tech overtime
game, and the 2024-season FCS championship. The October 26 audit found 40, 73,
34 and 47 unambiguous links respectively. Those are limited rush/pass matches,
not full-game coverage claims. The overtime fixture does **not** establish
successful overtime matching; its incomplete native period/drive context remains
explicitly unresolved. Synthetic high-level tests cover overtime separation,
ambiguity, penalties and conflicting scores.

Opt into the separate bulk-source audit:

```powershell
.venv\Scripts\python.exe -m sports_analyst.datasets.cfb_source_audit --cfbd-cache data/source-audits --output docs/audits/cfb-source-audit.json
```

This downloads the public **cfbfastR CFBD-derived** 2025 season asset once
(131,185,522 bytes at audit time), verifies its published SHA-256, and reuses the
content-addressed local cache. This is not a direct CFBD API sample. Only selected
game rows and columns are collected through a lazy scan. Downloads have size and
time limits, atomic publication and partial-file cleanup. No key is required, no
new dependency is added, and normal investigations do not download this asset.

The sampled game contained 206 rows, including 202 populated EPA and 200 WPA
values. Its metadata supplies a processing timestamp but no verified model
identity. These values are retained in raw inputs but are not mixed into existing
SportsDataverse model comparisons. The upstream documentation distinguishes model
generations: [cfbfastR model guide](https://cfbfastr.sportsdataverse.org/articles/college-football-expected-points-model-fundamentals-part-i.html).

Raw caches and generated audit reports remain ignored by Git. The audit cache is
local tooling; production acquisition separately uses the application's durable
cache/lease and manifest infrastructure.

## Verification and genuine limits

High-level tests exercise production acquisition, conflict-preserving resolution,
private cache reuse across durable replicas, input-manifest lineage, clearing,
retryable failures and the existing game-tablet flow. A live production NCAA
adapter check added formation context on 40 of 207 source events for the selected
2025 game. A live current-model run processed 200 plays with EPA and spread-free
WPA; this is a processed sample, not a claim that every source event is modeled.
The CFBD-derived sample corroborated 135 play links after validating lossless
IDs, sequence, situation, end position and cumulative scoreboard context. Its
legacy modeled values were not copied into resolved analysis rows.
A live production overtime check retained all 215 ESPN events, including all 37
overtime events, while supplementing only 34 corroborated regulation plays. No
unverified native overtime periods were assigned.

Unverified secondary overtime periods/possessions remain unknown, but they no
longer block or remove the primary overtime plays. No source adapter can recover
facts absent from its payload. No tracking, full snap lineup or coverage
assignment is manufactured. The CFBD float64 `id_play` field can lose digits:
only a lossless suffix plus verified game/context may corroborate an ESPN play ID.
Scoring-event indicators are not treated as cumulative scoreboard values.

Source rights are not automatically cleared by this code; confirmation settings
are an operator assertion. Other sports still need their own source audits before
adapters are extended to them.

Public access to a repository is not a blanket redistribution license. This
increment reads published artifacts only: it does not scrape protected NCAA
pages, install scraping transports or bypass access controls.
