# Download raw data into data/raw/ (Windows PowerShell 5+ / PowerShell 7).
# Usage: powershell -ExecutionPolicy Bypass -File scripts\download_data.ps1 [-ArchiveCommit <sha>]
param([string]$ArchiveCommit = "5d38b63cc93285b293a60eac750cb7923be75417")
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$oss = "https://aliopentrace.oss-cn-beijing.aliyuncs.com/v2020GPUTraces"
New-Item -ItemType Directory -Force -Path "data\raw\v2020" | Out-Null
foreach ($f in "pai_job_table", "pai_task_table", "pai_machine_spec") {
    $tgz = "data\raw\v2020\$f.tar.gz"
    if (-not (Test-Path $tgz)) { Invoke-WebRequest -Uri "$oss/$f.tar.gz" -OutFile $tgz }
    # tar.exe ships with Windows 10 1803+ and Windows 11.
    if (-not (Test-Path "data\raw\v2020\$f.csv")) { tar -xzf $tgz -C "data\raw\v2020" }
}

$archive = "data\raw\carbon-intensity-forecast-tracking"
if (-not (Test-Path $archive)) {
    # Shallow + sparse: the full history is several GB and large clones tend to drop.
    git clone --filter=blob:none --no-checkout --sparse https://github.com/nmpowell/carbon-intensity-forecast-tracking $archive
    git -C $archive sparse-checkout set --no-cone /data/db/2023/ /data/db/2024/ /data/db/reference.sqlite /README.md
}
git -C $archive checkout --quiet $ArchiveCommit
Write-Host "archive commit: $(git -C $archive rev-parse HEAD)"

uv run python scripts/audit_v2020.py --raw data/raw/v2020
uv run flipwise ingest alibaba
uv run flipwise ingest carbon
uv run flipwise validate
