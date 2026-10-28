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
| `raw/carbon-intensity-forecast-tracking/` | Clone of the NESO forecast-vintage archive, checked out at the pinned commit | no |
| `raw/carbon/neso_portal_regional_ci.csv` | NESO Data Portal regional carbon intensity (one value per region per half-hour, 2018-09 to 2026-07). Used only as the regional truth cross-check (PRD §6.2), **not** as the scheduler's forecast | no |
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

Source: <https://github.com/nmpowell/carbon-intensity-forecast-tracking> (MIT). Pinned commit: recorded in `manifests/carbon_archive.json` by `flipwise ingest carbon`. To reproduce exactly, pass that commit to the download script (`bash scripts/download_data.sh <commit>` or `-ArchiveCommit <commit>`).

## NESO Data Portal (cross-check only)

Regional carbon intensity forecast: <https://www.neso.energy/data-portal/regional-carbon-intensity-forecast>. Save as `raw/carbon/neso_portal_regional_ci.csv`.
