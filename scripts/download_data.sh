#!/usr/bin/env bash
# Download raw data into data/raw/ (Linux, macOS, Git Bash on Windows).
# Usage: bash scripts/download_data.sh [ARCHIVE_COMMIT]
set -euo pipefail
cd "$(dirname "$0")/.."

OSS=https://aliopentrace.oss-cn-beijing.aliyuncs.com/v2020GPUTraces
mkdir -p data/raw/v2020
for f in pai_job_table pai_task_table pai_machine_spec; do
  [ -f "data/raw/v2020/$f.tar.gz" ] || curl -fL -o "data/raw/v2020/$f.tar.gz" "$OSS/$f.tar.gz"
  [ -f "data/raw/v2020/$f.csv" ] || tar -xzf "data/raw/v2020/$f.tar.gz" -C data/raw/v2020
done

ARCHIVE=data/raw/carbon-intensity-forecast-tracking
[ -d "$ARCHIVE" ] || git clone https://github.com/nmpowell/carbon-intensity-forecast-tracking "$ARCHIVE"
if [ -n "${1:-}" ]; then git -C "$ARCHIVE" checkout --quiet "$1"; fi
echo "archive commit: $(git -C "$ARCHIVE" rev-parse HEAD)"

uv run python scripts/audit_v2020.py --raw data/raw/v2020
