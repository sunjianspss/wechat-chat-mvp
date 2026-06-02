param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$InputPath,

    [Parameter(Position = 1)]
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not $env:UV_CACHE_DIR) {
    $env:UV_CACHE_DIR = Join-Path $env:TEMP "uv-cache"
}

$arguments = @(
    "run",
    "--python",
    "3.12",
    "python",
    "wechat_analyzer.py",
    "summarize",
    $InputPath
)

if ($OutputPath) {
    $arguments += @("-o", $OutputPath)
}

& uv @arguments
exit $LASTEXITCODE
