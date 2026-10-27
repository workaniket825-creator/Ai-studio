"""OCR provider abstraction. Backends: off | local (Tesseract) | api (an OCR Model Endpoint,
e.g. Azure Document Intelligence via a configured endpoint). Honest-guarded: if the engine or
credentials aren't present, returns a clear not-executed marker instead of fabricating text.

Text-layer detection lets us skip OCR on digital PDFs (the fast path) and only OCR image pages.
"""
from __future__ import annotations


def needs_ocr(page_text: str) -> bool:
    """Heuristic: a page with almost no extractable text is likely scanned → needs OCR."""
    return len((page_text or "").strip()) < 20


def ocr_available(backend: str) -> bool:
    if backend == "local":
        try:
            import pytesseract  # noqa: F401
            from PIL import Image  # noqa: F401
            return True
        except Exception:
            return False
    return backend == "api"


def ocr_image_bytes(img_bytes: bytes, cfg: dict) -> tuple[str, bool]:
    """OCR a single image. Returns (text, executed). executed=False when guarded (no engine)."""
    backend = cfg.get("backend", "off")
    if backend == "off":
        return "", False
    if backend == "local":
        try:
            import io
            import pytesseract
            from PIL import Image
            lang = cfg.get("language", "eng")
            txt = pytesseract.image_to_string(Image.open(io.BytesIO(img_bytes)), lang=lang)
            return txt or "", True
        except Exception:
            return "", False   # Tesseract not installed → honest skip
    if backend == "api" and cfg.get("endpoint_id"):
        try:
            return _api_ocr(img_bytes, cfg["endpoint_id"]), True
        except Exception:
            return "", False
    return "", False


def _api_ocr(img_bytes: bytes, endpoint_id: str) -> str:
    """OCR via a configured Model Endpoint. Dispatches by the endpoint's provider:
      - azure_docai  → Azure AI Document Intelligence (prebuilt-read REST)
      - google_docai → Google Cloud Document AI (process REST)
      - anything else with vision (mistral/openai/gemini) → vision-LLM via LiteLLM
    Guarded: raises if the concrete call can't run here, so the caller records not-executed."""
    from ..endpoints import get_full
    ep = get_full(endpoint_id)
    if not ep:
        raise RuntimeError("OCR endpoint not found")
    provider = (ep.get("provider") or "").lower()
    if provider == "azure_docai":
        return _azure_docai(img_bytes, ep)
    if provider == "google_docai":
        return _google_docai(img_bytes, ep)
    return _vision_llm_ocr(img_bytes, ep)


def _vision_llm_ocr(img_bytes: bytes, ep: dict) -> str:
    import base64
    from ..endpoints import litellm_call_args
    args = litellm_call_args(ep)
    import litellm
    b64 = base64.b64encode(img_bytes).decode()
    resp = litellm.completion(model=args["model"], messages=[{"role": "user", "content": [
        {"type": "text", "text": "Extract all text from this document image verbatim."},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
    ]}], **args.get("params", {}))
    return resp["choices"][0]["message"]["content"] or ""


def _azure_docai(img_bytes: bytes, ep: dict) -> str:
    """Azure AI Document Intelligence — prebuilt-read (submit → poll → collect lines).
    Uses api_base (resource endpoint) + api_key. SSRF-guarded via security_net."""
    import time
    import urllib.request
    from ..security_net import check_url, BlockedURLError
    base = (ep.get("api_base") or "").rstrip("/")
    key = ep.get("api_key") or ""
    if not base or not key:
        raise RuntimeError("azure_docai needs api_base + api_key")
    version = ep.get("api_version") or "2023-07-31"
    url = f"{base}/formrecognizer/documentModels/prebuilt-read:analyze?api-version={version}"
    check_url(url)
    req = urllib.request.Request(url, data=img_bytes, method="POST", headers={
        "Ocp-Apim-Subscription-Key": key, "Content-Type": "application/octet-stream"})
    resp = urllib.request.urlopen(req, timeout=30)
    op = resp.headers.get("Operation-Location")
    if not op:
        raise RuntimeError("azure_docai: no Operation-Location returned")
    check_url(op)
    for _ in range(30):
        time.sleep(1)
        r = urllib.request.urlopen(urllib.request.Request(
            op, headers={"Ocp-Apim-Subscription-Key": key}), timeout=30)
        import json as _j
        body = _j.loads(r.read().decode())
        if body.get("status") in ("succeeded", "failed"):
            if body["status"] == "failed":
                raise RuntimeError("azure_docai analyze failed")
            return body.get("analyzeResult", {}).get("content", "") or ""
    raise RuntimeError("azure_docai: timed out")


def _google_docai(img_bytes: bytes, ep: dict) -> str:
    """Google Cloud Document AI — processors:process. Needs api_base (processor URL) +
    api_key (or bearer). Kept guarded: raises if not configured/usable here."""
    import base64
    import json as _j
    import urllib.request
    from ..security_net import check_url
    url = ep.get("api_base") or ""
    key = ep.get("api_key") or ""
    if not url or not key:
        raise RuntimeError("google_docai needs api_base (processor URL) + api_key")
    check_url(url)
    payload = _j.dumps({"rawDocument": {
        "content": base64.b64encode(img_bytes).decode(), "mimeType": "application/pdf"}}).encode()
    req = urllib.request.Request(url, data=payload, method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    r = urllib.request.urlopen(req, timeout=60)
    body = _j.loads(r.read().decode())
    return body.get("document", {}).get("text", "") or ""
