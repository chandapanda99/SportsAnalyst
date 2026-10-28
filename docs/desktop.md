# Windows desktop

The desktop edition runs the same FastAPI service and compiled Svelte application inside a native WebView2 window. It binds the API to a random loopback-only port for the
life of the window. Synced datasets and investigation history stay in the normal per-user data directory, so upgrades and uninstallations do not remove them.

New installers default to `%LOCALAPPDATA%\Programs\OpenSportsAnalyst\<version>`, with prerelease suffixes included. They do not reuse an earlier install directory, so different releases do not mix bundled Python/native runtime files. The application identity remains stable and shortcuts target the newly installed release. Older binary folders (including the old unversioned directory) are not automatically removed; this is not independent side-by-side installation management. Reinstalling the same version still targets its existing folder, so use a new version for a new release. Data, settings and credentials remain shared across releases; a versioned binary folder does not make older versions compatible with newer data schemas or resolve Windows App Control/signing restrictions. Close the running app before upgrading.

On first launch, the application asks for the model provider, analysis model, optional chat model, and credentials. API keys are stored in Windows Credential Manager; the
remaining preferences are stored in `%LOCALAPPDATA%\open-sports-analyst\desktop.json`. Select **Use deterministic mode** to run without an LLM. To reopen model setup from a
development installation, run `uv run sports-analyst-desktop --configure`.

Workspace startup identifies the settings/catalog requests still loading and provides a retryable error if they stall. Health checks have a 5-second deadline and ordinary
requests through the shared API client have a 30-second deadline, including response-body loading; long-running sync and analysis progress streams are not cut off by that
deadline. Investigation
history loads independently with its own loading indicator and retry action, so it does not prevent opening the investigation form. Optional sports-provider libraries
load when their feature is used. Missing or Windows-blocked provider libraries produce a feature-specific error without preventing access to the core app or existing
local data; core runtime libraries such as DuckDB and Polars are still required. These changes do not disable or bypass Windows application-control policies.

The desktop automatically stores its queue and progress history in `%LOCALAPPDATA%\open-sports-analyst\jobs.sqlite3` and starts `sports-analyst-worker` as a managed sibling
process. It needs no database server or cloud storage. Closing the desktop stops the active child cleanly; unfinished work is released back to the SQLite queue and resumes
when the application starts again. The command-line development server keeps the simpler in-process `JOB_BACKEND=local` default.

Desktop worker diagnostics persist in `<data directory>/logs/` (normally `%LOCALAPPDATA%\open-sports-analyst\logs\`).
`desktop-worker.log` records worker startup, job attempts, and child exits; `desktop-job.log` records application diagnostics and exception chains,
including failed soccer schedule requests. Each log rotates at 2 MiB and retains three backups. Credential environment values, URLs, bearer tokens,
and common credential assignments are redacted; review logs before sharing them. Sync errors identify the sport/league, season, dataset, and last reported step
without displaying raw provider exceptions. This context is also retained by cloud jobs; cloud diagnostics continue using platform console logs.

## Build the installer

The build collects DLLs from the declared desktop runtime dependency tree (including `xgboost/lib/xgboost.dll`) and preserves their package-relative paths.
It also includes XGBoost, SportsDataverse, and nflreadpy package resources, including XGBoost's required `VERSION` file.
The frozen smoke test loads NFL and SportsDataverse providers and exercises core native data libraries offline before producing an installer.
Missing required packages or DLLs fail the build. Native extension modules and system dependencies are additionally handled by PyInstaller's analysis/hooks;
this is not a guarantee against Windows policy blocks or every future dependency issue, so test releases on a clean Windows machine as well.

Install [uv](https://docs.astral.sh/uv/), Node.js 20+, and [Inno Setup 6](https://jrsoftware.org/isinfo.php), then run from a 64-bit Windows PowerShell terminal:

```powershell
./packaging/windows/build.ps1
```

The script verifies that `uv.lock` is current, builds the frontend from an isolated staging copy (so a running Vite server cannot lock packaging dependencies), synchronizes
the locked `desktop` and `desktop-build` dependency groups, and creates a PyInstaller
one-directory application. It then runs the frozen executable in an isolated smoke-test mode before downloading Microsoft's WebView2 evergreen bootstrapper and writing the
installer to `dist/installer/`. The frozen bundle includes the managed SQLite worker while cloud-only R2 and Google dependencies remain outside the desktop package.
Use `-SkipFrontend` only when `frontend/dist` is already current, or `-SkipInstaller` to stop after producing and smoke-testing the unpackaged desktop application.

For Authenticode signing, set either `WINDOWS_SIGNING_PFX_PATH` (and optionally `WINDOWS_SIGNING_PFX_PASSWORD`) or `WINDOWS_SIGNING_CERT_THUMBPRINT` before building. The build
signs and verifies both the executable and installer. Unsigned builds may run where device policy permits. Windows can warn or block unsigned or untrusted binaries; signing only the installer does not establish trust for every bundled native dependency.

The version is set once in `pyproject.toml`. Python package metadata, the API, and the installer build use that value. The private frontend package has no separate application
version. A release tag must match the project version (for example, `v1.0.0` for `1.0.0`); `-alpha`, `-beta`, and `-rc` suffixes are supported for prereleases.

The `Windows desktop installer` GitHub Actions workflow produces the same installer for version tags and manual runs. Add repository secrets
`WINDOWS_SIGNING_PFX_BASE64` and `WINDOWS_SIGNING_PFX_PASSWORD` to sign CI artifacts; without them, the workflow intentionally produces an unsigned artifact.
CI validates release tags and the lockfile, runs the desktop/dataset regression tests and frontend checks, and builds the frontend before packaging.
GitHub Actions skips the frozen provider smoke test; backend and frontend regression tests still run. Local builds run the smoke test by default, with `-SkipSmokeTest`
available to opt out. Failed CI packaging runs upload available PyInstaller warning logs as a diagnostics artifact. CI builds do not validate the packaged runtime, so test the
installer before distributing it.
The temporary CI signing certificate is removed even when a build fails. Signing covers the application EXE and installer, not every third-party native module;
a successful hosted-runner build does not guarantee acceptance by a user's application-control policy.
Local password-prompt builds can still use `~/certs/dev-signing.pfx`; `-SkipSigning` explicitly produces an unsigned build.

## Publish with GitHub Releases

Push the matching version tag to build and publish a GitHub release automatically:

```powershell
git tag v1.0.0
git push origin v1.0.0
```

The workflow attaches the versioned Windows x64 installer and its SHA-256 checksum to the release and generates notes that you can edit in GitHub. Tags with `-alpha`,
`-beta`, or `-rc` publish prereleases. A manual workflow run creates a
downloadable Actions artifact for verification but does not publish a release. Public downloads require a public repository; for a private source repository, publish from a
separate public distribution repository instead.

See [environment settings](environment.md) for model configuration and the difference between local-server and desktop workers.
