# Appends any missing "## " sections from global-claude-md-additions.md into
# %USERPROFILE%\.claude\CLAUDE.md. Append-only and idempotent: an existing
# section with the same heading is left untouched.

$src = Join-Path $PSScriptRoot 'global-claude-md-additions.md'
if (-not (Test-Path -LiteralPath $src)) { Write-Output "missing source: $src"; exit 1 }

$target = Join-Path $env:USERPROFILE '.claude\CLAUDE.md'
New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null

$existing = ''
if (Test-Path -LiteralPath $target) {
    $raw = Get-Content -Raw -LiteralPath $target
    if ($raw) { $existing = $raw }
}
$before = $existing.Length

$text = Get-Content -Raw -LiteralPath $src
$blocks = [regex]::Split($text, '(?m)^(?=## )') | Where-Object { $_.Trim() -ne '' }

$added = @()
foreach ($b in $blocks) {
    $heading = ($b -split "`n")[0].Trim()
    if ($existing -like "*$heading*") { continue }
    Add-Content -LiteralPath $target -Value ''
    Add-Content -LiteralPath $target -Value $b.TrimEnd()
    $added += $heading
}

if ($added.Count -eq 0) {
    Write-Output "no change - all sections already present: $target"
} else {
    Write-Output "added to $target :"
    $added | ForEach-Object { Write-Output "  $_" }
}
Write-Output ("size: " + $before + " -> " + (Get-Item -LiteralPath $target).Length + " bytes")
