# Data

Raw and processed data are **never committed** (`.gitignore`). Recreate them with:

```bash
bash scripts/download_data.sh            # Linux / macOS / Git Bash
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\download_data.ps1   # Windows
```

## Layout

| Path | Content | Committed |
|---|---|---|
| `raw/v2020/` | Alibaba GPU trace v2020 archives and extracted CSVs | no |
| `raw/india/` | `grid-india/psp/` daily PSP reports, `mendeley/` SCADA workbooks, and the constructed `india_generation.csv` (`region_id,slot_utc,fuel,mwh`; `region_id` 1 NR, 2 WR, 3 SR, 4 ER) | no |
| `raw/cea/` | CEA CO2 Baseline Database User Guide v19.0 (emission factors in `configs/energy.yaml`) | no |
| `raw/carbon-intensity-forecast-tracking/` | Clone of the NESO forecast-vintage archive at the pinned commit. Source of real forecast-error paths only (PRD v0.5 §6.2.3); the simulated world is Indian | no |
| `raw/carbon/neso_portal_regional_ci.csv` | NESO Data Portal regional carbon intensity (2018-09 to 2026-07). Cross-check for the GB truth `A_gb` that the error paths are measured against | no |
| `processed/` | Output of `flipwise ingest` | no |
| `manifests/` | JSON manifests: sources, checksums, commits, row counts | yes |

## Alibaba Cluster Trace GPU v2020

Source: <https://github.com/alibaba/clusterdata/tree/master/cluster-trace-gpu-v2020>. Research/study use; cite Weng et al., NSDI '22.

| Archive | SHA-256 |
|---|---|
| `pai_job_table.tar.gz` | `5aad7f7caac501136d14ed6a48e40546f825d7b0617a3a4f337e2348fe0a6cb0` |
| `pai_task_table.tar.gz` | `cd1d6dc3215d2a8607ccf6b6dd952b5db776df86926c73259fea7c1499ac40e5` |
| `pai_machine_spec.tar.gz` | `cc0d38a4045af1b1af8179de8b1b54b1ddd995e6160d6d061a6b1000f1276c2d` |

Manual download: `https://aliopentrace.oss-cn-beijing.aliyuncs.com/v2020GPUTraces/<archive>`, then `tar -xzf <archive> -C data/raw/v2020` (`tar` is built into Windows 10+).

## NESO forecast-vintage archive

Source: <https://github.com/nmpowell/carbon-intensity-forecast-tracking> (MIT). Pinned commit: `5d38b63cc93285b293a60eac750cb7923be75417` (also recorded in `manifests/carbon_archive.json`). The full history is several GB and large clones tend to drop; the download script does a shallow, sparse clone of only `data/db/2023`, `data/db/2024` and `reference.sqlite` (about 540 MB). To reproduce exactly, pass that commit to the download script (`bash scripts/download_data.sh <commit>` or `-ArchiveCommit <commit>`).

## Indian generation by fuel and CEA factors (PRD §6.2.2, v0.7)

Constructed from two Grid-India sources: regional daily generation by fuel from the NLDC daily Power Supply Position reports, shaped within each IST day by all-India SCADA generation by fuel (10-second data on Mendeley Data, CC BY 4.0, doi:10.17632/y58jknpgs8.2). About 330 small report files and about 500 MB of SCADA workbooks; SHA-256 per file in `manifests/india_raw.json`. CEA factors (v19.0, Table 6) are already in `configs/energy.yaml`.

```bash
uv sync --extra india-data                        # openpyxl + xlrd, only for reading the reports
uv run python scripts/download_india.py           # re-runnable; skips files already present
uv run python scripts/build_india_generation.py   # → raw/india/india_generation.csv + manifests/india_generation.json
uv run flipwise ingest india --generation data/raw/india/india_generation.csv
uv run flipwise build-forecasts
uv run flipwise validate
```

## NESO Data Portal (cross-check only)

Regional carbon intensity forecast: <https://www.neso.energy/data-portal/regional-carbon-intensity-forecast>. Save as `raw/carbon/neso_portal_regional_ci.csv`.
