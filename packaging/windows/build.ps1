param(
    [string] $Version = "0.1.0",
    [switch] $SkipFrontend,
    [switch] $SkipInstaller
)

$ErrorActionPreference = "Stop"
$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDirectory "..\..")).Path
$frontendDirectory = Join-Path $projectRoot "frontend"
$distributionDirectory = Join-Path $projectRoot "dist"
$executable = Join-Path $distributionDirectory "OpenSportsAnalyst\OpenSportsAnalyst.exe"
$vendorDirectory = Join-Path $scriptDirectory "vendor"
$webViewInstaller = Join-Path $vendorDirectory "MicrosoftEdgeWebview2Setup.exe"

Push-Location $projectRoot
try
{
    if (-not $SkipFrontend)
    {
        # Do not run npm ci in the development checkout. On Windows, an active
        # Vite process keeps Rollup's native module loaded and npm cannot unlink
        # it. Build from a disposable copy so packaging remains reproducible
        # without disturbing a running development server.
        $frontendStagingRoot = Join-Path $projectRoot "build\frontend-packaging"
        $frontendStagingDirectory = Join-Path $frontendStagingRoot ([Guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $frontendStagingDirectory -Force | Out-Null
        try
        {
            foreach ($relativePath in @(
                "package.json",
                "package-lock.json",
                "index.html",
                "svelte.config.js",
                "tsconfig.json",
                "vite.config.ts",
                "public",
                "src"
            ))
            {
                $source = Join-Path $frontendDirectory $relativePath
                if (-not (Test-Path -LiteralPath $source))
                {
                    throw "Frontend build input is missing: $source"
                }
                Copy-Item -LiteralPath $source -Destination $frontendStagingDirectory -Recurse -Force
            }

            Push-Location $frontendStagingDirectory
            try
            {
                npm ci
                if ($LASTEXITCODE -ne 0)
                {
                    throw "npm ci failed in isolated frontend staging directory"
                }
                npm run build
                if ($LASTEXITCODE -ne 0)
                {
                    throw "Frontend build failed"
                }
            }
            finally
            {
                Pop-Location
            }

            $stagedFrontendOutput = Join-Path $frontendStagingDirectory "dist"
            if (-not (Test-Path -LiteralPath $stagedFrontendOutput))
            {
                throw "Frontend build completed without producing $stagedFrontendOutput"
            }
            $frontendOutput = Join-Path $frontendDirectory "dist"
            if (Test-Path -LiteralPath $frontendOutput)
            {
                Remove-Item -LiteralPath $frontendOutput -Recurse -Force
            }
            Copy-Item -LiteralPath $stagedFrontendOutput -Destination $frontendOutput -Recurse -Force
        }
        finally
        {
            $resolvedBuildRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot "build"))
            $resolvedStagingDirectory = [IO.Path]::GetFullPath($frontendStagingDirectory)
            if (-not $resolvedStagingDirectory.StartsWith(
                    $resolvedBuildRoot + [IO.Path]::DirectorySeparatorChar,
                    [StringComparison]::OrdinalIgnoreCase
            ))
            {
                throw "Refusing to clean unexpected frontend staging path: $resolvedStagingDirectory"
            }
            if (Test-Path -LiteralPath $resolvedStagingDirectory)
            {
                Remove-Item -LiteralPath $resolvedStagingDirectory -Recurse -Force
            }
        }
    }
    Write-Host "Frontend Files: BUILT"

    uv lock --check
    if ($LASTEXITCODE -ne 0)
    {
        throw "uv.lock is stale; run uv lock and commit the result before packaging"
    }

    uv sync --frozen --extra desktop --extra desktop-build
    if ($LASTEXITCODE -ne 0)
    {
        throw "Desktop dependencies could not be synchronized"
    }
    Write-Host "Desktop dependencies: SYNCHRONIZED"

    uv run python packaging/windows/make_icon.py
    if ($LASTEXITCODE -ne 0)
    {
        throw "Application icon generation failed"
    }
    Write-Host "App Icon: GENERATED"

    uv run pyinstaller --noconfirm --clean --distpath dist --workpath build/desktop packaging/windows/OpenSportsAnalyst.spec
    if ($LASTEXITCODE -ne 0)
    {
        throw "PyInstaller build failed"
    }
    Write-Host "PyInstaller Build: SUCCESS!"

    if (-not (Test-Path -LiteralPath $executable))
    {
        throw "PyInstaller completed without producing $executable"
    }

    # Exercise the actual frozen executable with isolated local settings. This
    # catches missing frontend assets, hidden imports, and multiprocessing
    # bootstrap failures before an installer is produced.
    $smokeDataDirectory = Join-Path $projectRoot "build\desktop-smoke-data"
    New-Item -ItemType Directory -Path $smokeDataDirectory -Force | Out-Null
    $smokeLog = Join-Path $projectRoot "build\desktop-smoke-test.log"
    if (Test-Path -LiteralPath $smokeLog)
    {
        Remove-Item -LiteralPath $smokeLog -Force
    }
    $smokeEnvironment = @{
        DATA_DIR = $smokeDataDirectory
        JOB_BACKEND = "local"
        PERSISTENCE_BACKEND = "local"
        SPORTS_ANALYST_SMOKE_LOG = $smokeLog
    }
    $previousEnvironment = @{ }
    foreach ($name in $smokeEnvironment.Keys)
    {
        $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
        [Environment]::SetEnvironmentVariable($name, $smokeEnvironment[$name], "Process")
    }
    try
    {
        $smokeTest = Start-Process -FilePath $executable -ArgumentList "--smoke-test" -WindowStyle Hidden -Wait -PassThru
        $smokeExitCode = $smokeTest.ExitCode
    }
    finally
    {
        foreach ($name in $previousEnvironment.Keys)
        {
            [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
        }
    }
    if ($smokeExitCode -ne 0)
    {
        $details = if (Test-Path -LiteralPath $smokeLog)
        {
            Get-Content -LiteralPath $smokeLog -Raw
        }
        else
        {
            "No diagnostic log was produced"
        }
        throw "Frozen desktop smoke test failed with exit code $smokeExitCode`n$details"
    }
    if (Test-Path -LiteralPath $smokeLog)
    {
        Remove-Item -LiteralPath $smokeLog -Force
    }
    Write-Host "Frozen Desktop Smoke Test: SUCCESS!"

    $signingConfigured = [bool]($env:WINDOWS_SIGNING_PFX_PATH -or $env:WINDOWS_SIGNING_CERT_THUMBPRINT)
    if ($signingConfigured)
    {
        & "$scriptDirectory\sign.ps1" -Path $executable
    }
    if ($SkipInstaller)
    {
        Write-Host "Desktop Application built at $executable"
        exit 0
    }

    New-Item -ItemType Directory -Path $vendorDirectory -Force | Out-Null
    if (-not (Test-Path -LiteralPath $webViewInstaller))
    {
        Invoke-WebRequest -UseBasicParsing -Uri "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -OutFile $webViewInstaller
    }

    $iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
    if (-not $iscc)
    {
        $candidate = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
        if (Test-Path -LiteralPath $candidate)
        {
            $iscc = $candidate
        }
    }
    if (-not $iscc)
    {
        $candidate = Join-Path ${env:ProgramFiles} "Inno Setup 6\ISCC.exe"
        if (Test-Path -LiteralPath $candidate)
        {
            $iscc = $candidate
        }
    }
    if (-not $iscc)
    {
        $candidate = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 7\ISCC.exe"
        if (Test-Path -LiteralPath $candidate)
        {
            $iscc = $candidate
        }
    }
    if (-not $iscc)
    {
        $candidate = Join-Path ${env:ProgramFiles} "Inno Setup 7\ISCC.exe"
        if (Test-Path -LiteralPath $candidate)
        {
            $iscc = $candidate
        }
    }
    if (-not $iscc)
    {
        throw "Inno Setup was not found. Install it, then rerun this script."
    }

    & $iscc "/DMyAppVersion=$Version" "$scriptDirectory\OpenSportsAnalyst.iss"
    if ($LASTEXITCODE -ne 0)
    {
        throw "Inno Setup compilation FAILED"
    }

    $installer = Get-ChildItem -LiteralPath (Join-Path $distributionDirectory "installer") -Filter "OpenSportsAnalyst-$Version-*-setup.exe" |
            Select-Object -First 1 -ExpandProperty FullName
    if (-not $installer)
    {
        throw "The installer output was not found"
    }
    if ($signingConfigured)
    {
        & "$scriptDirectory\sign.ps1" -Path $installer
    }
    Write-Host "Windows Installer BUILT!" -ForegroundColor Green -BackgroundColor DarkMagenta
}
finally
{
    Pop-Location
}
