# Secondary CFB sources: usage review and deployment settings

Reviewed October 26, 2026. This records published statements, not legal advice or
a grant of rights. The operator must determine whether their intended private,
desktop-distribution or hosted use is permitted before enabling these sources.

| Source                         | Observed terms                                                                                                                                                                                                                                               | Implementation consequence                                                                                                                                                                                                                                   |
|--------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| NCAA published captures        | The [raw repository](https://github.com/sportsdataverse/ncaa-mfb-football-raw) and [processed repository](https://github.com/sportsdataverse/ncaa-mfb-football-data) had no declared license in GitHub repository metadata.                                  | No claim of blanket reuse/redistribution rights. Disabled until operator confirmation; contact maintainers if permission is unclear. Published assets only; no protected-page scraping.                                                                      |
| CFBD-derived cfbfastR releases | [CFBD terms](https://collegefootballdata.com/terms), effective August 12, 2026, allow application use, private caching and derived analysis, but prohibit raw-feed/bulk redistribution. Product-specific licenses take precedence for downloadable products. | The adapter uses published SportsDataverse release assets, not a keyed CFBD API. API permissions alone do not establish permission for every third-party asset; confirm intended use. Do not bundle raw seasons with installers or offer a raw-data service. |
| SportsDataverse distribution   | The [distribution repository](https://github.com/sportsdataverse/sportsdataverse-data) declares MIT. Upstream data and third-party rights still need separate consideration.                                                                                 | Retain attribution and input source receipts. No inference that a software license licenses all underlying content.                                                                                                                                          |

The existing ESPN integration and its source terms remain applicable. The new
adapters do not relax access controls, add shared API credentials, or grant rights
to logos, likenesses or other third-party material. No provider was contacted or
permission obtained on the operator's behalf.

## Enable only after confirming your use

In the server/worker environment (or the desktop launch environment):

```dotenv
CFB_SECONDARY_USAGE_CONFIRMED=true
CFB_NCAA_ENABLED=true
CFB_CFBD_ENABLED=true
```

Defaults are false. Confirmation is an operator assertion, not automated legal
clearance. Settings fail explicitly if a source is enabled without confirmation.
Use the same settings on API and worker processes; restart after changing them.
The source catalog endpoint reports effective activation and confirmation state.

No new API key, provider package, hosted integration or LLM is required. CFBD is
optional independently of NCAA: leave `CFB_CFBD_ENABLED=false` to avoid its bulk
season asset. Enabling CFBD can download one season asset (at most 160 MiB) per
release checksum; disk and private durable-storage costs remain the operator's.
The app never bundles these downloaded assets into an installer. Under feature
policy `cfb-features-1`, CFBD bulk acquisition occurs only during explicit source
review/audits: it is not a routine rendering or analysis dependency. Enabling a
provider permits its approved uses; it does not force a download for every feature.

Both adapters use bounded requests, private provider/version-scoped caches and
the existing durable leases. Source errors are retryable and do not remove ESPN
plays. Current seasons refresh; historical successful payloads are reused.
Clearing CFB data removes the provider caches and catalog records as well.

This feature does not add a raw-download endpoint. A public deployment operator
must still review existing report/export surfaces, storage access policies and
their overall use; this review is not a certification of that deployment.
