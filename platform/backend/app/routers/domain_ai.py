"""Domain AI section APIs. Decision Intelligence FT = /api/v1/domain-ai/dfm/*"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from ..modules.domain_ai import dfm

router = APIRouter(prefix="/api/v1/domain-ai", tags=["domain-ai"])


@router.get("/dfm/assessments")
def list_assessments():
    return dfm.list_assessments()


@router.post("/dfm/assessments")
def create_assessment(body: dict):
    try:
        return dfm._summary_row(dfm.create(body.get("state"), body.get("summary")))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/dfm/assessments/{aid}")
def get_assessment(aid: str):
    rec = dfm.get(aid)
    if not rec:
        raise HTTPException(404, "assessment not found")
    return rec


@router.put("/dfm/assessments/{aid}")
def update_assessment(aid: str, body: dict):
    try:
        rec = dfm.update(aid, body.get("state"), body.get("summary"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not rec:
        raise HTTPException(404, "assessment not found")
    return dfm._summary_row(rec)


@router.delete("/dfm/assessments/{aid}")
def delete_assessment(aid: str):
    if not dfm.delete(aid):
        raise HTTPException(404, "assessment not found")
    return {"ok": True}


@router.post("/dfm/assessments/{aid}/ai-report")
async def ai_report(aid: str, body: dict):
    """Run the module's own LLM prompt on a platform Model Endpoint (off the event loop)."""
    try:
        return await asyncio.to_thread(dfm.generate_ai_report, aid, body.get("endpoint_id") or "",
                                       body.get("prompt") or "")
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(424, f"Model call failed: {str(e)[:400]}")


@router.post("/dfm/assessments/{aid}/word")
def word_report(aid: str, body: dict):
    try:
        return dfm.save_word(aid, body.get("report") or {}, bool(body.get("include_ai_report", True)))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Could not create the Word report: {str(e)[:300]}")
