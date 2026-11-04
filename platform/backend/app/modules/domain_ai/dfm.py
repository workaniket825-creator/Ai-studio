"""Decision Intelligence FT - backend for the Decision Framework for Model Tuning (v3).

The framework itself (gates, questions, verdict logic) runs in the browser module unchanged;
the backend owns persistence and the two platform add-ons:
  * shared, multi-assessment storage  (collection `dfm_assessments`, JSON or Postgres store)
  * AI report: send the module's own LLM prompt to a platform Model Endpoint
  * Word report: build a .docx and save it to File Storage
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from ...store import make_repo

repo = make_repo("dfm_assessments", "id")
FILES_DIR = "domain-ai/decision-intelligence-ft"
MAX_STATE_BYTES = 2_000_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _meta(state: dict) -> dict:
    m = (state or {}).get("meta") or {}
    return {"name": m.get("assessmentName") or "Untitled assessment", "client": m.get("client") or "",
            "industry": m.get("industry") or "", "lead_consultant": m.get("leadConsultant") or "",
            "started_at": m.get("startedAt"), "framework_version": m.get("frameworkVersion") or ""}


def validate_state(state) -> dict:
    if not isinstance(state, dict) or not isinstance(state.get("meta"), dict):
        raise ValueError("not a valid assessment: 'meta' is missing")
    for k in ("answers", "notes", "verdicts", "rationales"):
        if k in state and not isinstance(state[k], dict):
            raise ValueError(f"not a valid assessment: '{k}' must be an object")
    import json
    if len(json.dumps(state)) > MAX_STATE_BYTES:
        raise ValueError("assessment is too large")
    return state


def _summary_row(rec: dict) -> dict:
    out = {k: v for k, v in rec.items() if k not in ("state", "ai_report")}
    ai = rec.get("ai_report") or {}
    out["has_ai_report"] = bool(ai.get("markdown"))
    out["ai_report_at"] = ai.get("generated_at")
    return out


def list_assessments() -> list[dict]:
    rows = [_summary_row(r) for r in repo.list()]
    return sorted(rows, key=lambda r: r.get("updated_at") or "", reverse=True)


def get(aid: str) -> dict | None:
    return repo.get(aid)


def create(state: dict, summary: dict | None = None, actor: str = "user") -> dict:
    validate_state(state)
    now = _now()
    rec = {"id": f"dfm_{uuid.uuid4().hex[:12]}", **_meta(state), "summary": summary or {},
           "state": state, "ai_report": None, "created_at": now, "updated_at": now,
           "created_by": actor, "updated_by": actor}
    return repo.upsert(rec)


def update(aid: str, state: dict, summary: dict | None = None, actor: str = "user") -> dict | None:
    rec = repo.get(aid)
    if not rec:
        return None
    validate_state(state)
    rec.update({**_meta(state), "state": state, "updated_at": _now(), "updated_by": actor})
    if summary is not None:
        rec["summary"] = summary
    return repo.upsert(rec)


def delete(aid: str) -> bool:
    return repo.delete(aid)


# ------------------------------------------------------------------ AI report (Model Endpoint)
def generate_ai_report(aid: str, endpoint_id: str, prompt: str, max_tokens: int = 6000) -> dict:
    rec = repo.get(aid)
    if not rec:
        raise LookupError("assessment not found")
    if not (prompt or "").strip():
        raise ValueError("empty prompt")
    from ...endpoints import get_full, litellm_call_args
    ep = get_full(endpoint_id)
    if not ep:
        raise ValueError("model endpoint not found - add one in Model Endpoints")
    try:
        import litellm
    except Exception as e:
        raise RuntimeError("the LLM runtime (litellm) is not installed on the backend") from e
    args = litellm_call_args(ep)
    resp = litellm.completion(model=args["model"], messages=[{"role": "user", "content": prompt}],
                              max_tokens=max_tokens, temperature=0.2, **args["params"])
    text = (resp.choices[0].message.content or "").strip()
    if not text:
        raise RuntimeError("the model returned an empty report")
    usage = getattr(resp, "usage", None)
    report = {"markdown": text, "endpoint_id": endpoint_id,
              "model": ep.get("name") or ep.get("model"), "generated_at": _now(),
              "in_tokens": getattr(usage, "prompt_tokens", None),
              "out_tokens": getattr(usage, "completion_tokens", None)}
    rec["ai_report"] = report
    repo.upsert(rec)
    return report


# ------------------------------------------------------------------ Word report (File Storage)
def _md_sections(md: str) -> list[dict]:
    """Small markdown -> docgen sections (headings, paragraphs, bullets)."""
    sections: list[dict] = []
    cur: dict = {}
    para: list[str] = []

    def flush_para():
        if para:
            txt = " ".join(p.strip() for p in para).strip()
            if txt:
                sections.append({"text": re.sub(r"\*\*(.+?)\*\*", r"\1", txt)})
            para.clear()

    for line in (md or "").splitlines():
        s = line.rstrip()
        h = re.match(r"^(#{1,4})\s+(.*)", s)
        b = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)", s)
        if h:
            flush_para()
            sections.append({"heading": re.sub(r"\*\*(.+?)\*\*", r"\1", h.group(2)).strip(),
                             "level": min(len(h.group(1)) + 1, 4)})
        elif b:
            flush_para()
            item = re.sub(r"\*\*(.+?)\*\*", r"\1", b.group(1)).strip()
            if sections and "bullets" in sections[-1] and "heading" not in sections[-1]:
                sections[-1]["bullets"].append(item)
            else:
                sections.append({"bullets": [item]})
        elif not s.strip() or s.strip().startswith("|---") or s.strip() == "---":
            flush_para()
        else:
            para.append(s.replace("|", " ").strip() if s.strip().startswith("|") else s)
    flush_para()
    return sections


def _table(headers: list[str], rows: list[list]) -> dict:
    """docgen renders tables from dict rows (keyed by header)."""
    return {"headers": headers, "rows": [dict(zip(headers, (str(c) for c in r))) for r in rows]}


def build_word(aid: str, report: dict, include_ai_report: bool = True) -> tuple[bytes, dict]:
    rec = repo.get(aid)
    if not rec:
        raise LookupError("assessment not found")
    if not isinstance(report, dict) or not isinstance(report.get("gates"), list):
        raise ValueError("report model is missing")
    from ...docgen import _docx_bytes
    m = report.get("meta") or {}
    sm = report.get("summary") or {}
    sections: list[dict] = [
        {"text": "TCS Domain AI Studio · Domain AI › Decision Intelligence FT · "
                 "Decision Framework for Model Tuning " + str(m.get("frameworkVersion") or "v3.0")},
        {"heading": "Assessment", "level": 1, "table": _table(["Field", "Value"], [
            ["Assessment", m.get("assessmentName") or ""], ["Client", m.get("client") or ""],
            ["Industry", m.get("industry") or ""], ["Lead consultant", m.get("leadConsultant") or ""],
            ["Started", m.get("startedAt") or ""], ["Last updated", m.get("lastUpdatedAt") or ""],
            ["Questions answered", f"{sm.get('answered', 0)} / {sm.get('total_questions', 0)}"],
            ["Gates decided", f"{sm.get('gates_decided', 0)} / {sm.get('gates_total', 0)}"]])},
        {"heading": "Overall recommendation", "level": 1, "text": report.get("overall_label") or ""},
        {"heading": "Gate verdicts", "level": 1, "table": _table(["Gate", "Title", "Verdict"], [
            [g.get("num", ""), g.get("title", ""), g.get("verdict_label", "")] for g in report["gates"]])},
    ]
    if report.get("next_steps"):
        sections.append({"heading": "Next steps", "level": 1, "bullets": report["next_steps"]})
    ai = rec.get("ai_report") or {}
    if include_ai_report and ai.get("markdown"):
        sections.append({"heading": "AI-generated decision report", "level": 1,
                         "text": f"Generated with {ai.get('model')} on {ai.get('generated_at')}."})
        sections.extend(_md_sections(ai["markdown"]))
    sections.append({"heading": "Gate-by-gate detail", "level": 1})
    for g in report["gates"]:
        sections.append({"heading": f"Gate {g.get('num', '')} — {g.get('title', '')} "
                                    f"({g.get('verdict_label', '')})", "level": 2,
                         **({"text": f"Deliverable: {g['deliverable']}"} if g.get("deliverable") else {})})
        for d in g.get("dimensions") or []:
            rows = [[q.get("text", ""), q.get("answer") or "—"] for q in d.get("questions") or []]
            sections.append({"heading": f"{d.get('tag', '')} {d.get('title', '')} — {d.get('verdict_label', '')}",
                             "level": 3, "table": _table(["Question", "Answer"], rows)})
            if d.get("rationale"):
                sections.append({"text": f"Rationale: {d['rationale']}"})
            if d.get("notes"):
                sections.append({"text": f"Notes: {d['notes']}"})
    title = f"Fine-Tuning Decision Report — {m.get('assessmentName') or rec.get('name')}"
    data = _docx_bytes(title, None, sections)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", (m.get("assessmentName") or rec.get("name") or "assessment")).strip("-")[:60]
    fname = f"{slug or 'assessment'}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.docx"
    return data, {"filename": fname, "folder": FILES_DIR}


def save_word(aid: str, report: dict, include_ai_report: bool = True, actor: str = "user") -> dict:
    from ... import filestore
    data, info = build_word(aid, report, include_ai_report)
    saved = filestore.write_bytes(f"{info['folder']}/{info['filename']}", data, actor=actor)
    rec = repo.get(aid)
    if rec is not None:
        rec.setdefault("word_reports", [])
        rec["word_reports"] = ([{"path": saved["path"], "size": saved["size"], "created_at": _now()}]
                               + rec["word_reports"])[:20]
        repo.upsert(rec)
    return saved
