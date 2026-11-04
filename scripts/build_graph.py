"""Build the project graph: code from graphify's AST pass, decisions parsed from docs/decisions.md.

Decisions are parsed, not extracted by an LLM, so the graph holds exactly what the log says, costs
nothing to rebuild and needs no API key. The PRD is linked by section headings only.

Run from the repository root (graphify is a tool outside the project's dependencies, PRD §12.1):

    uv tool run --from graphifyy python scripts/build_graph.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

LOG = "docs/decisions.md"
PRD = "docs/prd.md"
OUT = Path("graphify-out")
MAX_LABEL = 80


def table_rows(section: str) -> list[list[str]]:
    """Body cells of every Markdown table row in `section`, skipping header and divider rows."""
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split(" | ")]
        for line in section.splitlines()
        if line.startswith("| ") and not line.startswith("| ID ")
    ]
    return [r for r in rows if not r[0].startswith("---")]


def code_modules(cell: str) -> list[str]:
    """Module names from a log row's Code cell, e.g. `planner, policies`; `—` means none yet."""
    return [] if cell == "—" else [m.strip() for m in cell.split(",")]


def _node(node_id: str, label: str, source: str, **attrs) -> dict:
    return {
        "id": node_id,
        "label": label if len(label) <= MAX_LABEL else label[: MAX_LABEL - 1] + "…",
        "file_type": "concept",
        "source_file": source,
        "source_location": None,
        "_origin": "semantic",
        **attrs,
    }


def _edge(source: str, target: str, relation: str, source_file: str = LOG) -> dict:
    return {
        "source": source,
        "target": target,
        "relation": relation,
        "confidence": "EXTRACTED",
        "confidence_score": 1.0,
        "source_file": source_file,
        "source_location": None,
        "weight": 1.0,
        "_origin": "semantic",
    }


def prd_sections(prd_text: str) -> dict[str, str]:
    """Numbered PRD headings: `{"10.4": "Stage 1: ..."}`."""
    found = re.findall(r"^#{2,4} (\d+(?:\.\d+)*)\.? (.+)$", prd_text, re.MULTILINE)
    return dict(found)


def decision_graph(log_text: str, prd_text: str) -> dict:
    """Nodes and edges for phases, decisions, findings and the PRD sections they cite."""
    sections = prd_sections(prd_text)
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for heading, body in re.findall(r"^## ([^\n]+)\n(.*?)(?=^## |\Z)", log_text, re.M | re.S):
        if heading == "Rules":
            continue
        is_findings = heading == "Findings"
        phase = None
        if not is_findings:
            phase = "phase_" + re.sub(r"\W+", "_", heading.split(":")[0].lower()).strip("_")
            nodes[phase] = _node(phase, f"Phase: {heading}", LOG)
        for row in table_rows(body):
            if is_findings:
                fid, date, finding, led_to, evidence = row
                node = f"finding_{fid.lower()}"
                nodes[node] = _node(
                    node, f"{fid}: {finding}", LOG, rationale=finding, date=date, evidence=evidence
                )
                for d in re.findall(r"D\d+", led_to):
                    edges.append(_edge(node, f"decision_{d.lower()}", "led_to"))
                continue
            did, date, decision, why, status, prd, code = row
            node = f"decision_{did.lower()}"
            nodes[node] = _node(
                node, f"{did}: {decision}", LOG, rationale=why, status=status, date=date
            )
            edges.append(_edge(node, phase, "decided_in"))
            for ref in re.findall(r"F\d+", why):
                edges.append(_edge(f"finding_{ref.lower()}", node, "justifies"))
            successor = re.fullmatch(r"superseded by (D\d+)", status)
            if successor:
                edges.append(_edge(node, f"decision_{successor.group(1).lower()}", "superseded_by"))
            for ref in re.findall(r"§(\d+(?:\.\d+)*)", prd):
                section = "prd_s" + ref.replace(".", "_")
                nodes.setdefault(
                    section, _node(section, f"PRD §{ref} {sections.get(ref, '')}".strip(), PRD)
                )
                edges.append(_edge(node, section, "specified_in"))
            for module in code_modules(code):
                edges.append(_edge(node, f"src_flipwise_{module}", "implemented_in"))
    return {"nodes": list(nodes.values()), "edges": edges, "hyperedges": []}


def _community_label(members: list[str], by_id: dict[str, dict]) -> str:
    """Name a community after its most common source file, so no LLM is needed."""
    # Members can be stubs graphify added for external names (e.g. `datetime`), absent from by_id.
    sources = (by_id.get(m, {}).get("source_file") for m in members)
    files = [Path(f).name for f in sources if f]
    return max(sorted(set(files)), key=files.count) if files else "misc"


def main() -> None:
    from graphify.analyze import god_nodes, suggest_questions, surprising_connections
    from graphify.build import build_from_json
    from graphify.cluster import cluster, score_all
    from graphify.detect import detect
    from graphify.export import to_html, to_json
    from graphify.extract import extract
    from graphify.report import generate

    OUT.mkdir(exist_ok=True)
    detection = detect(Path("."))
    code = [Path(f) for f in detection["files"]["code"]]
    ast = extract(code, cache_root=Path("."), root=Path("."))
    log_text = Path(LOG).read_text(encoding="utf-8")
    decisions = decision_graph(log_text, Path(PRD).read_text(encoding="utf-8"))
    extraction = {
        "nodes": ast["nodes"] + decisions["nodes"],
        "edges": ast["edges"] + decisions["edges"],
        "hyperedges": [],
        "input_tokens": 0,
        "output_tokens": 0,
    }
    (OUT / ".graphify_extract.json").write_text(json.dumps(extraction, indent=1), encoding="utf-8")

    graph = build_from_json(extraction, root=".")
    communities = cluster(graph)
    by_id = {n["id"]: n for n in extraction["nodes"]}
    labels = {c: _community_label(m, by_id) for c, m in communities.items()}
    # force: this script is the full build, so a smaller graph means code really was removed.
    to_json(graph, communities, str(OUT / "graph.json"), community_labels=labels, force=True)
    report = generate(
        graph,
        communities,
        score_all(graph, communities),
        labels,
        god_nodes(graph),
        surprising_connections(graph, communities),
        detection,
        {"input": 0, "output": 0},
        ".",
        suggested_questions=suggest_questions(graph, communities, labels),
    )
    (OUT / "GRAPH_REPORT.md").write_text(report, encoding="utf-8")
    to_html(graph, communities, str(OUT / "graph.html"), community_labels=labels)
    print(
        f"graph: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges; "
        f"{len(decisions['nodes'])} from the decision log"
    )


if __name__ == "__main__":
    main()
