#!/usr/bin/env python
"""Studio notebook job runner — executed ON the DSLab runtime, detached from Jupyter.

The DSLab MCP server (start_notebook_job) copies this file into the job directory
(<jupyter root>/studio-jobs/<job_id>/studio_runner.py) and launches it in its own process
group with the kernel's Python interpreter, so it keeps running if the browser, the SSH tunnel,
the MCP call or the platform backend goes away.

It executes the (already parameterised) notebook cell by cell and keeps a small status file
that the platform polls:

  status.json            state, current cell, progress bars, custom progress, log tail
  run.log                full stdout/stderr of every cell, as it happens
  executed.ipynb         the notebook with outputs (saved after every cell)
  outputs/               STUDIO_OUTPUT_DIR — where notebooks should write models/artifacts
  outputs_manifest.json  every file under outputs/ with size and sha256 (written at the end)

Progress conventions a notebook may use (both optional):
  * tqdm-style bars ("123/1000 [..") are picked up automatically from the output stream;
  * print a line  ##STUDIO_PROGRESS {"step": 10, "total_steps": 100, "loss": 0.42}
    to publish arbitrary progress values (shown live in Chat).

Only the standard library is needed to start. Execution uses nbclient (installed with Jupyter)
and falls back to an in-process IPython shell if nbclient is not available.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import signal
import sys
import threading
import time
import traceback
import urllib.request
from datetime import datetime, timezone

JOB_DIR = os.path.abspath(os.getcwd())
STATUS = os.path.join(JOB_DIR, "status.json")
LOG = os.path.join(JOB_DIR, "run.log")
OUT_DIR = os.path.join(JOB_DIR, "outputs")
MANIFEST = os.path.join(JOB_DIR, "outputs_manifest.json")

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_BAR = re.compile(r"(?:(?P<desc>[^\r\n|]{0,40}?):?\s*)?(?P<pct>\d{1,3})%\|[^|]*\|\s*(?P<n>\d+)/(?P<total>\d+)")
_BAR2 = re.compile(r"(?P<n>\d+)/(?P<total>\d+)\s*\[")
_MARK = "##STUDIO_PROGRESS"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class State:
    def __init__(self):
        self.lock = threading.RLock()
        self.data: dict = {
            "state": "starting", "pid": os.getpid(), "python": sys.executable,
            "started_at": _now(), "ended_at": None, "heartbeat": _now(),
            "cells": {"total": 0, "current": None, "completed": 0, "title": ""},
            "bar": None, "custom": {}, "log_tail": [], "error": "",
        }
        self.tail: collections.deque = collections.deque(maxlen=40)
        self.partial = ""
        self.cancel_reason = ""
        self._last_flush = 0.0
        self.log_fh = open(LOG, "a", buffering=1, encoding="utf-8", errors="replace")

    def update(self, **kw) -> None:
        with self.lock:
            self.data.update(kw)
            self.flush()

    def flush(self) -> None:
        with self.lock:
            self._last_flush = time.time()
            self.data["heartbeat"] = _now()
            self.data["log_tail"] = list(self.tail)[-25:]
            tmp = STATUS + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.data, f, default=str)
            os.replace(tmp, STATUS)

    def log(self, text: str) -> None:
        """Tee cell output: full log file + tail + progress parsing."""
        if not text:
            return
        with self.lock:
            self.log_fh.write(text)
            buf = self.partial + _ANSI.sub("", text)
            parts = buf.split("\n")
            self.partial = parts.pop()            # trailing incomplete line ("" if none)
            for raw in parts:
                self._parse(raw)
                line = raw.split("\r")[-1].rstrip()   # \r = progress bar redraw: keep the last
                if line:
                    self.tail.append(line[:400])
            if "\r" in self.partial:              # live progress-bar redraws without newline
                self._parse(self.partial)
                self.partial = self.partial.split("\r")[-1]
            if time.time() - self._last_flush > 2:   # keep status.json fresh, at most every 2 s
                self.flush()

    def _parse(self, raw: str) -> None:
        for seg in raw.split("\r"):
            if _MARK in seg:
                try:
                    payload = json.loads(seg.split(_MARK, 1)[1].strip())
                    if isinstance(payload, dict):
                        self.data.setdefault("custom", {}).update(payload)
                        self.data["custom_cell"] = (self.data.get("cells") or {}).get("current")
                except Exception:
                    pass
                continue
            m = _BAR.search(seg) or _BAR2.search(seg)
            if m:
                try:
                    n, total = int(m.group("n")), int(m.group("total"))
                    if total > 0 and n <= total:
                        desc = (m.groupdict().get("desc") or "").strip()
                        self.data["bar"] = {"n": n, "total": total, "desc": desc[:40], "ts": _now()}
                except Exception:
                    pass


S: State


def _heartbeat():
    while True:
        time.sleep(10)
        try:
            S.flush()
        except Exception:
            pass


def _check_mlflow():
    uri = os.environ.get("MLFLOW_TRACKING_URI", "")
    if not uri:
        S.update(mlflow_reachable=None, mlflow_detail="MLFLOW_TRACKING_URI not set")
        return
    if not uri.startswith(("http://", "https://")):
        S.update(mlflow_reachable=None, mlflow_detail=f"non-HTTP tracking URI {uri}")
        return
    try:
        with urllib.request.urlopen(uri.rstrip("/") + "/health", timeout=8) as r:
            ok = r.status == 200
        S.update(mlflow_reachable=ok, mlflow_detail=f"{uri} -> HTTP {r.status}")
    except Exception as e:
        S.update(mlflow_reachable=False, mlflow_detail=f"{uri} unreachable from the runtime: {e}")


def _cell_title(nb_cells, idx) -> str:
    """Nearest markdown heading above a code cell (used as a human label for progress)."""
    for j in range(idx, -1, -1):
        c = nb_cells[j]
        if c.get("cell_type") == "markdown":
            src = c.get("source", "")
            src = "".join(src) if isinstance(src, list) else src
            for line in src.splitlines():
                if line.strip().startswith("#"):
                    return line.strip("# ").strip()[:120]
    return ""


def _err_text(e) -> str:
    return _ANSI.sub("", str(e))[-4000:]


# ------------------------------------------------------------------ engines
def run_nbclient(nb_path: str, out_path: str) -> tuple[str, dict]:
    import nbformat
    from nbclient import NotebookClient
    from nbclient.exceptions import CellExecutionError

    class TeeClient(NotebookClient):
        def output(self, outs, msg, display_id, cell_index):  # stream outputs live
            try:
                t = msg.get("msg_type") or msg.get("header", {}).get("msg_type")
                c = msg.get("content", {})
                if t == "stream":
                    S.log(c.get("text", ""))
                elif t == "error":
                    S.log("\n".join(c.get("traceback") or [f"{c.get('ename')}: {c.get('evalue')}"]) + "\n")
                elif t in ("execute_result", "display_data"):
                    txt = (c.get("data") or {}).get("text/plain")
                    if txt:
                        S.log((txt if isinstance(txt, str) else "".join(txt)) + "\n")
            except Exception:
                pass
            return super().output(outs, msg, display_id, cell_index)

    nb = nbformat.read(nb_path, as_version=4)
    code_idx = [i for i, c in enumerate(nb.cells) if c.cell_type == "code" and str(c.source).strip()]
    S.update(engine="nbclient", cells={"total": len(code_idx), "current": None, "completed": 0, "title": ""})
    client = TeeClient(nb, timeout=None, kernel_name="python3", allow_errors=False,
                       resources={"metadata": {"path": JOB_DIR}})
    failed: dict = {}
    state = "completed"
    with client.setup_kernel():
        for k, i in enumerate(code_idx, 1):
            title = _cell_title(nb.cells, i)
            S.update(state="running", bar=None, cell_started_at=_now(),
                     cells={"total": len(code_idx), "current": i, "number": k,
                            "completed": k - 1, "title": title})
            S.log(f"\n===== cell {i} ({k}/{len(code_idx)}){' - ' + title if title else ''} =====\n")
            try:
                client.execute_cell(nb.cells[i], i)
            except CellExecutionError as e:
                failed = {"index": i, "number": k, "title": title, "detail": _err_text(e),
                          "ename": getattr(e, "ename", "") or "",
                          "evalue": _ANSI.sub("", str(getattr(e, "evalue", "") or ""))[:1000]}
                state = "failed"
                break
            except KeyboardInterrupt:
                state = S.cancel_reason or "cancelled"
                failed = {"index": i, "number": k, "title": title, "detail": f"stopped ({state})"}
                break
            finally:
                try:
                    nbformat.write(nb, out_path)
                except Exception:
                    pass
            S.update(cells={"total": len(code_idx), "current": i, "number": k, "completed": k,
                            "title": title})
    nbformat.write(nb, out_path)
    return state, failed


def run_ipython(nb_path: str, out_path: str) -> tuple[str, dict]:
    """Fallback when nbclient is unavailable: run cells in an in-process IPython shell."""
    import contextlib
    import io
    from IPython.core.interactiveshell import InteractiveShell

    with open(nb_path) as f:
        nb = json.load(f)
    cells = nb.get("cells", [])
    code_idx = [i for i, c in enumerate(cells) if c.get("cell_type") == "code"
                and ("".join(c["source"]) if isinstance(c.get("source"), list) else c.get("source", "")).strip()]
    S.update(engine="ipython", cells={"total": len(code_idx), "current": None, "completed": 0, "title": ""})
    shell = InteractiveShell.instance()

    class Tee(io.TextIOBase):
        def __init__(self, name):
            self.name, self.buf = name, []

        def write(self, s):
            self.buf.append(s)
            S.log(s)
            return len(s)

    failed: dict = {}
    state = "completed"
    for k, i in enumerate(code_idx, 1):
        c = cells[i]
        src = "".join(c["source"]) if isinstance(c.get("source"), list) else c.get("source", "")
        title = _cell_title(cells, i)
        S.update(state="running", bar=None, cell_started_at=_now(),
                 cells={"total": len(code_idx), "current": i, "number": k,
                        "completed": k - 1, "title": title})
        out, err = Tee("stdout"), Tee("stderr")
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                res = shell.run_cell(src, store_history=True)
        except KeyboardInterrupt:
            state = S.cancel_reason or "cancelled"
            failed = {"index": i, "number": k, "title": title, "detail": f"stopped ({state})"}
            break
        c["outputs"] = [{"output_type": "stream", "name": n, "text": "".join(t.buf)}
                        for n, t in (("stdout", out), ("stderr", err)) if t.buf]
        c["execution_count"] = k
        with open(out_path, "w") as f:
            json.dump(nb, f, indent=1)
        if not res.success:
            e = res.error_in_exec or res.error_before_exec
            failed = {"index": i, "number": k, "title": title, "detail": f"{type(e).__name__}: {e}",
                      "ename": type(e).__name__, "evalue": str(e)[:1000]}
            state = "failed"
            break
        S.update(cells={"total": len(code_idx), "current": i, "number": k, "completed": k, "title": title})
    with open(out_path, "w") as f:
        json.dump(nb, f, indent=1)
    return state, failed


# ------------------------------------------------------------------ outputs
def _manifest() -> dict:
    files, total = [], 0
    for root, _dirs, names in os.walk(OUT_DIR):
        for n in sorted(names):
            p = os.path.join(root, n)
            try:
                size = os.path.getsize(p)
                h = hashlib.sha256()
                with open(p, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
                files.append({"path": os.path.relpath(p, OUT_DIR), "size": size, "sha256": h.hexdigest()})
                total += size
            except Exception as e:
                files.append({"path": os.path.relpath(p, OUT_DIR), "error": str(e)})
    m = {"root": OUT_DIR, "files": files, "total_bytes": total, "generated_at": _now()}
    with open(MANIFEST, "w") as f:
        json.dump(m, f, indent=1)
    return m


def _log_outputs_to_mlflow(manifest: dict, max_gb: float) -> dict:
    run_id = os.environ.get("MLFLOW_RUN_ID", "")
    if not run_id:
        return {"logged": False, "detail": "no MLFLOW_RUN_ID"}
    if not manifest["files"]:
        return {"logged": False, "detail": "no output files"}
    if manifest["total_bytes"] > max_gb * (1 << 30):
        return {"logged": False, "detail": f"outputs exceed the {max_gb} GB MLflow upload limit"}
    try:
        from mlflow.tracking import MlflowClient
    except Exception:
        return {"logged": False, "detail": "mlflow is not installed in the runtime's Python"}
    try:
        MlflowClient().log_artifacts(run_id, OUT_DIR, artifact_path="outputs")
        return {"logged": True, "artifact_path": "outputs", "bytes": manifest["total_bytes"]}
    except Exception as e:
        return {"logged": False, "detail": f"{type(e).__name__}: {e}"[:500]}


def main() -> int:
    global S
    ap = argparse.ArgumentParser()
    ap.add_argument("--notebook", default="notebook.ipynb")
    ap.add_argument("--output-notebook", default="executed.ipynb")
    ap.add_argument("--timeout-hours", type=float, default=24.0)
    ap.add_argument("--log-outputs-to-mlflow", type=int, default=1)
    ap.add_argument("--mlflow-max-gb", type=float, default=20.0)
    a = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    os.environ["STUDIO_OUTPUT_DIR"] = OUT_DIR
    os.environ["STUDIO_JOB_DIR"] = JOB_DIR
    S = State()
    S.update(state="starting", output_dir=OUT_DIR, timeout_hours=a.timeout_hours)
    threading.Thread(target=_heartbeat, daemon=True).start()

    def _term(signum, _frm):
        if not S.cancel_reason:
            S.cancel_reason = "cancelled"
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)

    def _watchdog():
        deadline = time.time() + a.timeout_hours * 3600
        while time.time() < deadline:
            time.sleep(15)
        S.cancel_reason = "timeout"
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=_watchdog, daemon=True).start()

    _check_mlflow()
    state, failed = "failed", {}
    try:
        try:
            import nbclient  # noqa: F401
            import nbformat  # noqa: F401
            engine = run_nbclient
        except Exception:
            engine = run_ipython
        state, failed = engine(a.notebook, a.output_notebook)
    except KeyboardInterrupt:
        state = S.cancel_reason or "cancelled"
    except Exception as e:
        state = "failed"
        S.update(error=f"{type(e).__name__}: {e}"[:2000])
        S.log(traceback.format_exc())

    S.update(state="finalizing", failed_cell=failed or None)
    try:
        m = _manifest()
        S.update(outputs={"files": len(m["files"]), "bytes": m["total_bytes"]})
        if a.log_outputs_to_mlflow and S.data.get("mlflow_reachable") is not False:
            S.update(mlflow_artifacts=_log_outputs_to_mlflow(m, a.mlflow_max_gb))
    except Exception as e:
        S.update(manifest_error=str(e))
    S.update(state=state, ended_at=_now())
    S.log_fh.close()
    return 0 if state == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
