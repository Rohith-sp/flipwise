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
