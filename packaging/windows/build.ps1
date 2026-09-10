param(
    [string] $Version = "1.0.0",
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
try {
    if (-not $SkipFrontend) {
        Push-Location $frontendDirectory
        try {
            npm ci
            if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
            npm run build
            if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
        } finally {
            Pop-Location
        }
    }

    uv sync --extra desktop --extra desktop-build
    if ($LASTEXITCODE -ne 0) { throw "Desktop dependencies could not be synchronized" }
    uv run python packaging/windows/make_icon.py
    if ($LASTEXITCODE -ne 0) { throw "Application icon generation failed" }
    uv run pyinstaller --noconfirm --clean --distpath dist --workpath build/desktop packaging/windows/OpenSportsAnalyst.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

    $signingConfigured = [bool]($env:WINDOWS_SIGNING_PFX_PATH -or $env:WINDOWS_SIGNING_CERT_THUMBPRINT)
    if ($signingConfigured) { & "$scriptDirectory\sign.ps1" -Path $executable }
    if ($SkipInstaller) {
        Write-Host "Desktop application built at $executable"
        exit 0
    }

    New-Item -ItemType Directory -Path $vendorDirectory -Force | Out-Null
    if (-not (Test-Path -LiteralPath $webViewInstaller)) {
        Invoke-WebRequest -UseBasicParsing -Uri "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -OutFile $webViewInstaller
    }

    $iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
    if (-not $iscc) {
        $candidate = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
        if (Test-Path -LiteralPath $candidate) { $iscc = $candidate }
    }
    if (-not $iscc) { throw "Inno Setup 6 was not found. Install it, then rerun this script." }
    & $iscc "/DMyAppVersion=$Version" "$scriptDirectory\OpenSportsAnalyst.iss"
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed" }

    $installer = Get-ChildItem -LiteralPath (Join-Path $distributionDirectory "installer") -Filter "OpenSportsAnalyst-$Version-*-setup.exe" |
        Select-Object -First 1 -ExpandProperty FullName
    if (-not $installer) { throw "The installer output was not found" }
    if ($signingConfigured) { & "$scriptDirectory\sign.ps1" -Path $installer }
    Write-Host "Windows installer built at $installer"
} finally {
    Pop-Location
}
