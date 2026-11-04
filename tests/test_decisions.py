"""The decision log stays consistent with itself and with the PRD (docs/decisions.md rules)."""

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"
LOG = (DOCS / "decisions.md").read_text(encoding="utf-8")
PRD = (DOCS / "prd.md").read_text(encoding="utf-8")
ROW = re.compile(r"^\| (D\d+) \| [^|]+ \| .+ \| ([^|]+?) \| [^|]+ \| [^|]+ \|$", re.MULTILINE)


def _graph_script():
    spec = importlib.util.spec_from_file_location("build_graph", ROOT / "scripts/build_graph.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass-free, but `from __future__` needs a registered name
    spec.loader.exec_module(module)
    return module


def _rows() -> list[tuple[str, str]]:
    return ROW.findall(LOG)


def _prd_version() -> str:
    return re.search(r"^\| Version \| ([\d.]+) \|$", PRD, re.MULTILINE).group(1)


def test_decision_ids_are_unique():
    ids = [d for d, _ in _rows()]
    assert ids and len(ids) == len(set(ids))


def test_statuses_are_valid_and_supersede_links_exist():
    ids = {d for d, _ in _rows()}
    for decision, status in _rows():
        match = re.fullmatch(r"superseded by (D\d+)", status)
        assert status in {"active", "proposed", "rejected"} or match, (decision, status)
        if match:
            assert match.group(1) in ids, decision


def test_every_prd_decision_is_in_the_log():
    in_prd = set(re.findall(r"^\| (D\d+) \|", PRD, re.MULTILINE))
    assert in_prd and in_prd <= {d for d, _ in _rows()}


def test_findings_point_at_decisions_that_exist():
    ids = {d for d, _ in _rows()}
    for finding, led_to in re.findall(r"^\| (F\d+) \| [^|]+ \| [^|]+ \| ([^|]+) \|", LOG, re.M):
        assert set(re.findall(r"D\d+", led_to)) <= ids, finding


def test_log_and_handoff_name_the_current_prd_version():
    version = _prd_version()
    assert f"**PRD version: {version}**" in LOG
    assert f"**PRD version: {version}**" in (DOCS / "HANDOFF.md").read_text(encoding="utf-8")


def test_code_column_names_real_modules():
    script = _graph_script()
    for line in re.findall(r"^\| D\d+ \|.*\| ([^|]+) \|$", LOG, re.MULTILINE):
        for module in script.code_modules(line.strip()):
            assert (ROOT / "src" / "flipwise" / f"{module}.py").exists(), module


def test_decision_graph_has_every_row_and_only_known_endpoints():
    """Parses without graphify installed; every edge lands on a parsed node or a code module."""
    graph = _graph_script().decision_graph(LOG, PRD)
    ids = {n["id"] for n in graph["nodes"]}
    assert {f"decision_{d.lower()}" for d, _ in _rows()} <= ids
    assert {f"finding_f{i}" for i in range(1, 6)} <= ids
    for edge in graph["edges"]:
        assert edge["source"] in ids, edge
        assert edge["target"] in ids or edge["target"].startswith("src_flipwise_"), edge
    d7 = next(e for e in graph["edges"] if e["relation"] == "superseded_by")
    assert (d7["source"], d7["target"]) == ("decision_d7", "decision_d19")
    assert any(n["id"] == "prd_s10_4" and "Stage 1" in n["label"] for n in graph["nodes"])
