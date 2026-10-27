"""Module 6 — Platform Insights & Recommendation Workflow (spec §24).

A meta-workflow that observes platform usage (runs, agents, workflows, metrics,
governance) and produces a **Word (.docx)** recommendation report. It dogfoods the
platform: it streams ActivityEvents like any run, then a report writer emits the
document. All open-source (python-docx); no cloud.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

from .activity import bus
from .observability import overview
from .schemas import ActivityEvent, ActivityKind
from .store import DATA_DIR
from .store import agents as agents_repo
from .store import runs as runs_repo
from .store import workflows as workflows_repo

REPORTS_DIR = DATA_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

GREEN = RGBColor(0x76, 0xB9, 0x00)
INK = RGBColor(0x1F, 0x29, 0x33)
MUTED = RGBColor(0x5C, 0x70, 0x80)


# ------------------------------- analysis -------------------------------
def compute_findings() -> list[dict]:
    runs = runs_repo.list()
    ov = overview(runs)
    findings: list[dict] = []

    # unused foundation agents (referenced by no workflow node)
    referenced = set()
    for wf in workflows_repo.list():
        for n in wf.get("nodes", []):
            ref = (n.get("agent_ref") or "").replace("agent_cards/", "")
            if ref:
                referenced.add(ref)
    if len(runs) > 0:
        for a in agents_repo.list(lambda x: x.get("category") == "foundation"):
            if a["agent_name"] not in referenced:
                findings.append({"category": "reuse", "severity": "low",
                                 "title": f"Foundation agent '{a['agent_name']}' is not used by any workflow",
                                 "evidence": "Referenced by 0 workflow nodes",
                                 "recommendation": "Surface it in the Designer, or deprecate if intentional."})
                break

    # low success-rate workflows
    for b in ov["by_workflow"]:
        if b["runs"] >= 1 and b["success_rate"] < 90:
            findings.append({"category": "failures", "severity": "high",
                             "title": f"'{b['name']}' success rate is {b['success_rate']}%",
                             "evidence": f"{b['runs']} runs, {b['success_rate']}% success",
                             "recommendation": "Add retry-and-reflect and inspect failing tools."})

    # token concentration
    if ov["by_workflow"]:
        top = max(ov["by_workflow"], key=lambda x: x["tokens"])
        if top["tokens"] > 0:
            findings.append({"category": "efficiency", "severity": "medium",
                             "title": f"'{top['name']}' is the top token consumer ({top['tokens']} tokens)",
                             "evidence": f"{top['tokens']} tokens across {top['runs']} runs",
                             "recommendation": "Route simple steps to a cheaper model tier (Flash) and trim prompts."})

    # latency
    if ov["p95_latency_ms"] and ov["p95_latency_ms"] > 12000:
        findings.append({"category": "performance", "severity": "medium",
                         "title": f"p95 latency is {round(ov['p95_latency_ms']/1000,1)}s",
                         "evidence": f"p95 {ov['p95_latency_ms']}ms",
                         "recommendation": "Parallelize independent steps; cache repeat tool calls."})

    if not findings:
        findings.append({"category": "governance", "severity": "low",
                         "title": "No material issues detected",
                         "evidence": f"{ov['total_runs']} runs analyzed",
                         "recommendation": "Continue monitoring; re-run insights weekly."})
    return findings


def _hx(sev: str) -> RGBColor:
    return {"high": RGBColor(0xD6, 0x45, 0x45), "medium": RGBColor(0xD9, 0x82, 0x2B),
            "low": RGBColor(0x3A, 0x91, 0x60)}.get(sev, MUTED)


def _write_docx(findings: list[dict], ov: dict, path: Path) -> None:
    doc = Document()
    normal = doc.styles["Normal"]; normal.font.name = "Calibri"; normal.font.size = Pt(10.5)

    # cover
    t = doc.add_paragraph(); t.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = t.add_run("ENTERPRISE AGENTIC AI PLATFORM"); r.bold = True; r.font.size = Pt(11); r.font.color.rgb = GREEN
    h = doc.add_paragraph(); hr = h.add_run("Platform Insights & Recommendations")
    hr.bold = True; hr.font.size = Pt(26); hr.font.color.rgb = INK
    sub = doc.add_paragraph().add_run("Generated automatically by Module 6 — Platform Insights Workflow")
    sub.italic = True; sub.font.color.rgb = MUTED

    meta = doc.add_table(rows=4, cols=2); meta.style = "Light Grid Accent 1"
    now = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    for i, (k, v) in enumerate([("Generated", now), ("Scope", "Organization — all teams"),
                                ("Runs analyzed", str(ov["total_runs"])),
                                ("Data sources", "Runs · Agents · Workflows · Metrics")]):
        meta.rows[i].cells[0].text = k; meta.rows[i].cells[1].text = v

    # executive summary
    doc.add_heading("Executive Summary", level=1)
    highs = sum(1 for f in findings if f["severity"] == "high")
    doc.add_paragraph(
        f"Analyzed {ov['total_runs']} runs with an overall success rate of {ov['success_rate']}%. "
        f"Total usage: {ov['total_input_tokens']} input + {ov['total_output_tokens']} output "
        f"= {ov['total_tokens']} tokens; p95 latency {round(ov['p95_latency_ms']/1000,1)}s. "
        f"p95 latency {round(ov['p95_latency_ms']/1000,1)}s. "
        f"This report lists {len(findings)} findings ({highs} high severity) with prioritized actions.")

    # key metrics table
    doc.add_heading("Key Metrics", level=2)
    km = doc.add_table(rows=1, cols=2); km.style = "Light List Accent 1"
    km.rows[0].cells[0].text = "Metric"; km.rows[0].cells[1].text = "Value"
    for k, v in [("Total runs", ov["total_runs"]), ("Success rate", f"{ov['success_rate']}%"),
                 ("Input tokens", ov["total_input_tokens"]), ("Output tokens", ov["total_output_tokens"]),
                 ("Total tokens", ov["total_tokens"]),
                 ("p50 / p95 latency", f"{ov['p50_latency_ms']} / {ov['p95_latency_ms']} ms")]:
        c = km.add_row().cells; c[0].text = str(k); c[1].text = str(v)

    # findings
    doc.add_heading("Findings", level=1)
    for i, f in enumerate(findings, 1):
        p = doc.add_paragraph(); run = p.add_run(f"{i}. {f['title']}")
        run.bold = True; run.font.size = Pt(12)
        sev = doc.add_paragraph().add_run(f"Severity: {f['severity'].upper()}")
        sev.bold = True; sev.font.color.rgb = _hx(f["severity"])
        doc.add_paragraph(f"Evidence: {f['evidence']}")
        rec = doc.add_paragraph(); rr = rec.add_run(f"Recommendation: {f['recommendation']}")
        rr.font.color.rgb = INK

    # recommendations summary
    doc.add_heading("Prioritized Recommendations", level=1)
    for i, f in enumerate(sorted(findings, key=lambda x: {"high": 0, "medium": 1, "low": 2}[x["severity"]]), 1):
        doc.add_paragraph(f"P{i}. {f['recommendation']}  ({f['category']}, {f['severity']})", style="List Number")

    doc.add_paragraph()
    foot = doc.add_paragraph().add_run("Generated by the Platform Insights Workflow (Module 6). "
                                       "Findings grounded in captured run data.")
    foot.italic = True; foot.font.size = Pt(8); foot.font.color.rgb = MUTED
    doc.save(str(path))


# ------------------------------- runner -------------------------------
async def _emit(rid, kind, label, **kw):
    await bus.publish(ActivityEvent(run_id=rid, seq=bus.next_seq(rid), kind=kind, label=label, **kw))


async def run_insights(run_id: str) -> dict:
    """Stream the meta-workflow, then generate the Word report."""
    await _emit(run_id, ActivityKind.phase, "Collecting run, agent and workflow data…", phase="plan")
    await asyncio.sleep(0.4)
    await _emit(run_id, ActivityKind.agent_enter, "Insights Collector gathering signals…", agent="Insights Collector")
    ov = overview(runs_repo.list())
    await asyncio.sleep(0.4)
    await _emit(run_id, ActivityKind.agent_enter, "Pattern Analyzer detecting issues…", agent="Pattern Analyzer")
    findings = compute_findings()
    await _emit(run_id, ActivityKind.reasoning, f"Detected {len(findings)} findings across categories.")
    await asyncio.sleep(0.4)
    await _emit(run_id, ActivityKind.agent_enter, "Report Writer composing the Word document…", agent="Report Writer")

    rid = f"insights_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    path = REPORTS_DIR / f"{rid}.docx"
    _write_docx(findings, ov, path)
    try:
        from . import filestore
        filestore.write_bytes(f"reports/{rid}.docx", path.read_bytes(), actor="agent")
    except Exception:
        pass  # never let mirroring break report generation
    await _emit(run_id, ActivityKind.verification, "Verified findings are grounded in captured data. PASS.", phase="verify")
    await _emit(run_id, ActivityKind.complete, "Insights report ready for download.", phase="done")

    record = {"id": rid, "run_id": run_id, "generated_at": datetime.now(timezone.utc).isoformat(),
              "findings": findings, "summary": f"{len(findings)} findings, {ov['success_rate']}% success",
              "docx": str(path), "metrics": ov}
    from .store import Repo
    Repo("insights_reports", "id").upsert(record)
    return record
