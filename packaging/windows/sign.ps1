param(
    [Parameter(Mandatory = $true)]
    [string[]] $Path
)

$ErrorActionPreference = "Stop"
$timestampUrl = if ($env:WINDOWS_TIMESTAMP_URL) { $env:WINDOWS_TIMESTAMP_URL } else { "http://timestamp.digicert.com" }
$signTool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
if (-not $signTool) {
    $kitsRoot = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    $signTool = Get-ChildItem -LiteralPath $kitsRoot -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
        Where-Object FullName -Match "\\x64\\signtool\.exe$" |
        Sort-Object FullName -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $signTool) { throw "signtool.exe was not found. Install the Windows SDK signing tools." }

foreach ($target in $Path) {
    $resolved = (Resolve-Path -LiteralPath $target).Path
    $arguments = @("sign", "/fd", "SHA256", "/td", "SHA256", "/tr", $timestampUrl)
    if ($env:WINDOWS_SIGNING_PFX_PATH) {
        $arguments += @("/f", $env:WINDOWS_SIGNING_PFX_PATH)
        if ($env:WINDOWS_SIGNING_PFX_PASSWORD) { $arguments += @("/p", $env:WINDOWS_SIGNING_PFX_PASSWORD) }
    } elseif ($env:WINDOWS_SIGNING_CERT_THUMBPRINT) {
        $arguments += @("/sha1", $env:WINDOWS_SIGNING_CERT_THUMBPRINT)
    } else {
        throw "Set WINDOWS_SIGNING_PFX_PATH or WINDOWS_SIGNING_CERT_THUMBPRINT before signing."
    }
    & $signTool @arguments $resolved
    if ($LASTEXITCODE -ne 0) { throw "Signing failed for $resolved" }
    & $signTool verify /pa /v $resolved
    if ($LASTEXITCODE -ne 0) { throw "Signature verification failed for $resolved" }
}
