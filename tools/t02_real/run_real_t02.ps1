# Run from any directory; defaults to candidate demonstration (NOT verified labels).
param(
    [ValidateSet('candidate','verified')][string]$Mode = 'candidate',
    [switch]$Collect
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $repo
try {
    $python = '.\.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) { throw 'Missing .venv Python; create the venv and install requirements first.' }
    $root = '.\data\real\t02_traffic_125'
    if ($Collect) {
        if (-not (Test-Path '.\tools\t02_data\fetch_traffic_125.py')) { throw 'Missing tools/t02_data/fetch_traffic_125.py; merge the collector branch or copy the tool first.' }
        Write-Host '[1/4] Try to complete missing candidate photos (Wikimedia Commons rate limits apply)...'
        & $python .\tools\t02_data\fetch_traffic_125.py --out $root --per-group 25 --pause 2.5
        if ($LASTEXITCODE -ne 0) { Write-Warning 'Collector incomplete: using the existing local candidates without inventing missing images.' }
    }
    Write-Host '[2/4] Prepare local T02 input and check provenance...'
    & $python -m tools.t02_real.prepare --root $root --mode $Mode
    if ($LASTEXITCODE -ne 0) { throw 'Dataset preparation failed. Inspect source_catalog.csv and selection_audit.csv.' }
    & $python -c "from pathlib import Path; from src.common.manifest import verify_manifest; p=Path('data/real/t02_traffic_125/ready/manifest.csv'); problems=verify_manifest(p); print('SHA-256 manifest:', 'PASS' if not problems else problems[:5]); assert not problems"
    if ($LASTEXITCODE -ne 0) { throw 'Manifest verification failed.' }
    Write-Host '[3/4] Core scoring + Leader review (offline)...'
    $out = if ($Mode -eq 'verified') { 'out/poc_real_verified' } else { 'out/poc_real' }
    & $python -m src.main --track t02 --config configs/lab.yaml --input data/real/t02_traffic_125/ready --output $out --offline --seed 42
    if ($LASTEXITCODE -ne 0) { throw 'Pipeline failed. Check that configs/lab.yaml has a non-TODO owner and Core is merged.' }
    Write-Host '[4/4] Output and human-review status:'
    Get-Content (Join-Path $out 'decision.json') -Encoding utf8
    Start-Process (Join-Path $out 'contact_sheet.html')
    Write-Host "Ready: $out/contact_sheet.html"
    Write-Warning 'An HTML review sheet is NOT ground truth. Evaluate the real set only after TV4 verifies labels and group splits.'
} finally {
    Pop-Location
}
