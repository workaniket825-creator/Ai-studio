"""Remote Jupyter client used by the DSLab runtime MCP server.

Talks to a DSLab JupyterLab through the backend's authenticated lab proxy
(/api/v1/dsl/runtimes/<rid>/lab/), which forwards over the runtime's SSH tunnel to
127.0.0.1 on the target and injects the lab token. Going through the proxy means:
  * the URL never changes (no ephemeral tunnel port),
  * Jupyter sees a loopback Host header (passes its remote-access check),
  * requests are token-authenticated (no XSRF rejections).

Only depends on httpx + websockets so it can run in a light stdio subprocess.
Kernel code runs over the standard Jupyter kernel websocket (JSON protocol v5.3).
"""
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class LabNotOpen(RuntimeError):
    """The runtime has no active SSH lab session (the proxy answered 404)."""


class LabError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text or "")


class LabClient:
    def __init__(self, base_url: str, token: str = "", timeout: float = 30.0):
        self.base = base_url.rstrip("/") + "/"
        self.headers = {"Authorization": f"token {token}"} if token else {}
        self.timeout = timeout
        self.session_id = uuid.uuid4().hex

    # ------------------------------------------------------------------ http
    def _url(self, path: str) -> str:
        return self.base + path.lstrip("/")

    def _req(self, method: str, path: str, **kw) -> httpx.Response:
        try:
            r = httpx.request(method, self._url(path), headers=self.headers,
                              timeout=kw.pop("timeout", self.timeout), **kw)
        except httpx.HTTPError as e:
            raise LabError(f"cannot reach the DSLab lab proxy at {self.base}: {e}") from e
        if r.status_code == 404 and "No active SSH lab" in r.text:
            raise LabNotOpen("no active lab session for this runtime")
        if r.status_code in (401, 403):
            raise LabError(f"Jupyter rejected the request (HTTP {r.status_code}). "
                           "Re-open the lab from DSLab so it restarts with the platform token.")
        if r.status_code >= 400:
            raise LabError(f"Jupyter API {method} {path} -> HTTP {r.status_code}: {r.text[:300]}")
        return r

    def status(self) -> dict:
        return self._req("GET", "api/status").json()

    # -------------------------------------------------------------- contents
    def get(self, path: str, content: bool = True) -> dict:
        p = path.strip("/")
        return self._req("GET", f"api/contents/{p}", params={"content": int(content)}).json()

    def list_dir(self, path: str = "") -> list[dict]:
        d = self.get(path, content=True)
        if d.get("type") != "directory":
            raise LabError(f"'{path}' is not a directory")
        return sorted(d.get("content") or [], key=lambda x: (x.get("type") != "directory", x.get("name", "")))

    def put_text(self, path: str, text: str) -> dict:
        body = {"type": "file", "format": "text", "content": text}
        return self._req("PUT", f"api/contents/{path.strip('/')}", json=body).json()

    def put_notebook(self, path: str, nb: dict) -> dict:
        body = {"type": "notebook", "format": "json", "content": nb}
        return self._req("PUT", f"api/contents/{path.strip('/')}", json=body).json()

    # --------------------------------------------------------------- kernels
    def ensure_session(self, path: str, kernel_name: str = "python3") -> str:
        """Return a live kernel id for `path` (reuses the existing session, so state persists)."""
        for s in self._req("GET", "api/sessions").json():
            if s.get("path") == path and s.get("kernel", {}).get("id"):
                kid = s["kernel"]["id"]
                k = self._req("GET", f"api/kernels/{kid}").json()
                if k.get("execution_state") != "dead":
                    return kid
        body = {"path": path, "name": path.split("/")[-1], "type": "notebook",
                "kernel": {"name": kernel_name}}
        s = self._req("POST", "api/sessions", json=body).json()
        return s["kernel"]["id"]

    def interrupt(self, kernel_id: str) -> None:
        try:
            self._req("POST", f"api/kernels/{kernel_id}/interrupt")
        except Exception:
            pass

    def restart(self, kernel_id: str) -> None:
        self._req("POST", f"api/kernels/{kernel_id}/restart", timeout=60)

    def _ws_url(self, kernel_id: str) -> str:
        base = self.base.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        return f"{base}api/kernels/{kernel_id}/channels?session_id={self.session_id}"

    def execute(self, kernel_id: str, code: str, timeout: float = 120.0) -> dict:
        """Run code in the kernel; return {status, outputs (nbformat), execution_count, timed_out}."""
        from websockets.sync.client import connect

        msg_id = uuid.uuid4().hex
        msg = {
            "header": {"msg_id": msg_id, "username": "dslab-agent", "session": self.session_id,
                       "msg_type": "execute_request", "version": "5.3", "date": _now()},
            "parent_header": {}, "metadata": {}, "channel": "shell", "buffers": [],
            "content": {"code": code, "silent": False, "store_history": True,
                        "user_expressions": {}, "allow_stdin": False, "stop_on_error": True},
        }
        outputs: list[dict] = []
        result = {"status": "ok", "outputs": outputs, "execution_count": None, "timed_out": False}
        got_idle = got_reply = False
        deadline = time.time() + max(5.0, float(timeout))
        try:
            ws = connect(self._ws_url(kernel_id), additional_headers=self.headers,
                         open_timeout=20, max_size=None)
        except Exception as e:
            raise LabError(f"could not open the kernel websocket: {e}") from e
        with ws:
            ws.send(json.dumps(msg))
            while not (got_idle and got_reply):
                remaining = deadline - time.time()
                if remaining <= 0:
                    self.interrupt(kernel_id)
                    result["timed_out"] = True
                    result["status"] = "timeout"
                    break
                try:
                    raw = ws.recv(timeout=remaining)
                except TimeoutError:
                    continue
                if isinstance(raw, (bytes, bytearray)):
                    continue  # binary frames carry buffers (widgets); not needed here
                m = json.loads(raw)
                if (m.get("parent_header") or {}).get("msg_id") != msg_id:
                    continue
                t = m.get("msg_type") or (m.get("header") or {}).get("msg_type")
                c = m.get("content") or {}
                if t == "stream":
                    if outputs and outputs[-1].get("output_type") == "stream" and outputs[-1]["name"] == c.get("name"):
                        outputs[-1]["text"] += c.get("text", "")
                    else:
                        outputs.append({"output_type": "stream", "name": c.get("name", "stdout"),
                                        "text": c.get("text", "")})
                elif t == "execute_result":
                    outputs.append({"output_type": "execute_result", "data": c.get("data", {}),
                                    "metadata": c.get("metadata", {}),
                                    "execution_count": c.get("execution_count")})
                elif t == "display_data":
                    outputs.append({"output_type": "display_data", "data": c.get("data", {}),
                                    "metadata": c.get("metadata", {})})
                elif t == "error":
                    outputs.append({"output_type": "error", "ename": c.get("ename", ""),
                                    "evalue": c.get("evalue", ""), "traceback": c.get("traceback", [])})
                    result["status"] = "error"
                elif t == "clear_output":
                    outputs.clear()
                elif t == "status" and c.get("execution_state") == "idle":
                    got_idle = True
                elif t == "execute_reply":
                    got_reply = True
                    result["execution_count"] = c.get("execution_count")
                    if c.get("status") and c.get("status") != "ok":
                        result["status"] = c.get("status")
        return result


def outputs_to_text(outputs: list[dict], limit: int = 15000) -> str:
    """Render nbformat outputs as plain text for an LLM."""
    parts: list[str] = []
    for o in outputs or []:
        ot = o.get("output_type")
        if ot == "stream":
            parts.append(o.get("text", ""))
        elif ot in ("execute_result", "display_data"):
            data = o.get("data") or {}
            if "text/plain" in data:
                tp = data["text/plain"]
                parts.append("".join(tp) if isinstance(tp, list) else str(tp))
            elif "text/html" in data:
                html = data["text/html"]
                html = "".join(html) if isinstance(html, list) else str(html)
                parts.append(re.sub(r"<[^>]+>", " ", html)[:2000])
            for mime in data:
                if mime.startswith("image/"):
                    parts.append(f"[{mime} output produced - not shown as text]")
        elif ot == "error":
            tb = "\n".join(strip_ansi(x) for x in (o.get("traceback") or []))
            parts.append(tb or f"{o.get('ename')}: {o.get('evalue')}")
    text = strip_ansi("".join(p if p.endswith("\n") else p + "\n" for p in parts if p))
    if len(text) > limit:
        text = text[: limit // 2] + f"\n... [{len(text) - limit} chars truncated] ...\n" + text[-limit // 2:]
    return text.strip()
