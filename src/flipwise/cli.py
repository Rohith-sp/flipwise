"""Command-line entry point (PRD §13.4)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _cmd_ingest_alibaba(args: argparse.Namespace) -> int:
    from flipwise.ingest import ingest_alibaba

    m = ingest_alibaba(args.raw, args.out, args.manifests, args.missing_gpu_policy)
    print(json.dumps({"rows": m["output"]["rows"], "dropped": m["dropped_by_reason"]}, indent=2))
    return 0


def _cmd_ingest_carbon(args: argparse.Namespace) -> int:
    import datetime as dt

    from flipwise.ingest import ingest_carbon

    rep = ingest_carbon(
        args.archive,
        dt.date.fromisoformat(args.start),
        dt.date.fromisoformat(args.end),
        [int(r) for r in args.gb_regions.split(",")],
        args.out,
        args.manifests,
    )
    keys = ("archive_commit", "rows", "forward_captures_per_day", "gb_truth_by_region")
    print(json.dumps({k: rep[k] for k in keys}, indent=2))
    return 0


def _cmd_ingest_india(args: argparse.Namespace) -> int:
    import pandas as pd
    import yaml

    from flipwise.carbon import interpolate_truth
    from flipwise.errors import ConfigError
    from flipwise.ingest import _base_manifest, india_truth
    from flipwise.trace import sha256_file

    energy = yaml.safe_load(args.factors.read_text())["emission_factors"]
    missing = [f for f, v in energy["g_per_kwh"].items() if v is None]
    if missing or not energy.get("cea_database_version"):
        raise ConfigError(
            f"{args.factors}: fill CEA factors {missing} and cea_database_version (blocker B4)"
        )
    gen = pd.read_csv(args.generation)
    raw = india_truth(gen, energy["g_per_kwh"])
    parts = []
    for r, grp in raw.groupby("region_id", sort=True):
        t = interpolate_truth(grp.set_index("slot_utc")["truth_g_per_kwh"])
        parts.append(t.assign(region_id=int(r)))
    truth = pd.concat(parts, ignore_index=True).assign(truth_kind=args.truth_kind)
    truth = truth[["region_id", "slot_utc", "truth_g_per_kwh", "truth_kind", "interpolated"]]
    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / "carbon_truth.csv"
    truth.to_csv(out, index=False, lineterminator="\n")
    man = {**_base_manifest(), "generation": str(args.generation),
           "generation_sha256": sha256_file(args.generation),
           "cea_database_version": energy["cea_database_version"],
           "factors_g_per_kwh": energy["g_per_kwh"], "truth_kind": args.truth_kind,
           "rows": len(truth), "outputs_sha256": {out.name: sha256_file(out)}}  # fmt: skip
    args.manifests.mkdir(parents=True, exist_ok=True)
    (args.manifests / "india_truth.json").write_text(json.dumps(man, indent=2) + "\n")
    print(f"wrote {out} ({len(truth)} rows)")
    return 0


def _cmd_build_forecasts(args: argparse.Namespace) -> int:
    import datetime as dt

    import pandas as pd

    from flipwise.config import load_config
    from flipwise.ingest import _base_manifest, _utc_midnight, build_forecasts, scale_factors
    from flipwise.trace import sha256_file

    cfg = load_config(args.config)
    d = cfg["data"]
    truth, errors, gb_truth = (pd.read_csv(d[k]) for k in ("truth", "gb_error_paths", "gb_truth"))
    mapping = {int(r): int(g) for r, g in cfg["error_source"].items()}
    lo_d, hi_d = (dt.date.fromisoformat(x) for x in cfg["splits"]["residual_fit_carbon"])
    s_r = scale_factors(truth, gb_truth, mapping, _utc_midnight(lo_d),
                        _utc_midnight(hi_d + dt.timedelta(days=1)) - 1)  # fmt: skip
    alpha = float(args.alpha if args.alpha is not None else cfg.get("alpha", 1.0))
    fc, counts = build_forecasts(truth, errors, mapping, s_r, alpha)
    out = Path(d["forecast"])
    out.parent.mkdir(parents=True, exist_ok=True)
    fc.to_csv(out, index=False, lineterminator="\n")
    man = {**_base_manifest(), "alpha": alpha, "error_source": mapping, "s_r": s_r, **counts,
           "rows": len(fc), "outputs_sha256": {out.name: sha256_file(out)}}  # fmt: skip
    Path(d["manifests"]).mkdir(parents=True, exist_ok=True)
    (Path(d["manifests"]) / "india_forecasts.json").write_text(json.dumps(man, indent=2) + "\n")
    print(json.dumps({"s_r": s_r, "rows": len(fc), **counts}, indent=2))
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    from flipwise.config import load_config
    from flipwise.validate import validate

    errs = validate(load_config(args.config))
    for e in errs:
        print("FAIL", e)
    print("validate: OK" if not errs else f"validate: {len(errs)} problems")
    return 1 if errs else 0


def _cmd_smoke(args: argparse.Namespace) -> int:
    from flipwise.smoke import TOY_DIR, smoke

    errs = smoke(args.scenario or TOY_DIR, args.out)
    for e in errs:
        print("MISMATCH", e)
    print("smoke: OK" if not errs else f"smoke: {len(errs)} mismatches")
    return 1 if errs else 0


def _cmd_run(args: argparse.Namespace) -> int:
    from flipwise.policies import make_policy
    from flipwise.reporting import write_run
    from flipwise.scenario import load_scenario
    from flipwise.simulator import Simulator

    sc = load_scenario(args.scenario)
    res = Simulator(sc, make_policy(args.policy)).run()
    out = args.out / f"{sc.name}_{args.policy}"
    hashes = write_run(res, out)
    print(f"wrote {out}")
    for name, h in hashes.items():
        print(f"  {name}  {h[:16]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="flipwise")
    sub = p.add_subparsers(dest="command", required=True)

    ing = sub.add_parser("ingest", help="raw data → canonical CSVs").add_subparsers(
        dest="source", required=True
    )
    a = ing.add_parser("alibaba", help="Alibaba GPU trace v2020")
    a.add_argument("--raw", type=Path, default=Path("data/raw/v2020"))
    a.add_argument("--out", type=Path, default=Path("data/processed"))
    a.add_argument("--manifests", type=Path, default=Path("data/manifests"))
    a.add_argument("--missing-gpu-policy", choices=["zero", "drop"], default="zero")
    a.set_defaults(func=_cmd_ingest_alibaba)

    c = ing.add_parser("carbon", help="NESO archive → GB forecast-error paths (§6.2.3)")
    c.add_argument("--archive", type=Path,
                   default=Path("data/raw/carbon-intensity-forecast-tracking"))  # fmt: skip
    c.add_argument("--start", default="2023-03-13")
    c.add_argument("--end", default="2024-02-08", help="last slot day, run tail included")
    c.add_argument("--gb-regions", default="13,7,9", help="error-source NESO region ids "
                   "(13 London, 7 South Wales, 9 East Midlands)")  # fmt: skip
    c.add_argument("--out", type=Path, default=Path("data/processed"))
    c.add_argument("--manifests", type=Path, default=Path("data/manifests"))
    c.set_defaults(func=_cmd_ingest_carbon)

    i = ing.add_parser("india", help="Indian generation by fuel → Indian truth (§6.2.2)")
    i.add_argument("--generation", type=Path, required=True,
                   help="CSV region_id,slot_utc,fuel,mwh (india_generation.csv)")  # fmt: skip
    i.add_argument("--factors", type=Path, default=Path("configs/energy.yaml"))
    i.add_argument("--truth-kind", default="generation_mix")
    i.add_argument("--out", type=Path, default=Path("data/processed"))
    i.add_argument("--manifests", type=Path, default=Path("data/manifests"))
    i.set_defaults(func=_cmd_ingest_india)

    bf = sub.add_parser("build-forecasts", help="Indian truth + GB error paths → vintages")
    bf.add_argument("--config", type=Path, default=Path("configs/base.yaml"))
    bf.add_argument("--alpha", type=float, default=None)
    bf.set_defaults(func=_cmd_build_forecasts)

    v = sub.add_parser("validate", help="check config, data, coverage and split separation")
    v.add_argument("--config", type=Path, default=Path("configs/base.yaml"))
    v.set_defaults(func=_cmd_validate)

    sm = sub.add_parser("smoke", help="toy scenario, all policies, compare to expected.yaml")
    sm.add_argument("--scenario", type=Path, default=None)
    sm.add_argument("--out", type=Path, default=Path("results/smoke"))
    sm.set_defaults(func=_cmd_smoke)

    r = sub.add_parser("run", help="one policy on one scenario → results/<name>_<policy>/")
    r.add_argument("--scenario", type=Path, required=True, help="scenario dir or scenario.yaml")
    r.add_argument("--policy", required=True)
    r.add_argument("--out", type=Path, default=Path("results"))
    r.set_defaults(func=_cmd_run)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
