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
COMMIT="${1:-5d38b63cc93285b293a60eac750cb7923be75417}"
if [ ! -d "$ARCHIVE" ]; then
  # Shallow + sparse: the full history is several GB and large clones tend to drop.
  git clone --filter=blob:none --no-checkout --sparse \
    https://github.com/nmpowell/carbon-intensity-forecast-tracking "$ARCHIVE"
  git -C "$ARCHIVE" sparse-checkout set --no-cone /data/db/2023/ /data/db/2024/ \
    /data/db/reference.sqlite /README.md
fi
git -C "$ARCHIVE" checkout --quiet "$COMMIT"
echo "archive commit: $(git -C "$ARCHIVE" rev-parse HEAD)"

uv run python scripts/audit_v2020.py --raw data/raw/v2020
uv run flipwise ingest alibaba
uv run flipwise ingest carbon        # GB error paths (PRD v0.5 §6.2.3)
uv run flipwise validate
