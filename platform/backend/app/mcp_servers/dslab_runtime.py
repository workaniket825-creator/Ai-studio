"""DSLab Runtime MCP server - gives agents code execution on a registered DSLab runtime.

Runs as a stdio subprocess of the backend (same pattern as the MLflow MCP server), so no extra
container, port or .env editing is needed. One registry entry exists per runtime
(id mcp_dslab_<runtime_id>), created from the DSLab screen with "Enable agent access".

Environment (set by the backend when it registers the server):
  DSLAB_RUNTIME_ID    runtime id (dsl_rt_...)
  DSLAB_RUNTIME_NAME  display name
  DSLAB_API_BASE      backend base URL, default http://127.0.0.1:8099
  DSLAB_LAB_URL       lab proxy URL (derived from the two above if unset)
  DSLAB_KERNEL        kernel name, default python3
  DSLAB_AUTO_OPEN     "1" (default): re-open the lab automatically when it is not running
"""
from __future__ import annotations

import json
import os
import textwrap

import httpx

try:  # mcp SDK 1.x
    from mcp.server.fastmcp import FastMCP as _Server
except ImportError:  # mcp SDK 2.x renamed FastMCP -> MCPServer
    from mcp.server.mcpserver import MCPServer as _Server

from app.modules.data_science_lab.jupyter_remote import (LabClient, LabError, LabNotOpen,
                                                         outputs_to_text)

RID = os.getenv("DSLAB_RUNTIME_ID", "")
NAME = os.getenv("DSLAB_RUNTIME_NAME", RID or "DSLab runtime")
API = os.getenv("DSLAB_API_BASE", "http://127.0.0.1:8099").rstrip("/")
LAB_URL = os.getenv("DSLAB_LAB_URL") or f"{API}/api/v1/dsl/runtimes/{RID}/lab/"
KERNEL = os.getenv("DSLAB_KERNEL", "python3")
AUTO_OPEN = os.getenv("DSLAB_AUTO_OPEN", "1") == "1"
AGENT_SESSION = ".dslab-agent-session.ipynb"   # persistent kernel shared by run_python/run_shell

server = _Server(
    "dslab-runtime",
    instructions=(f"Tools that execute code on the DSLab runtime '{NAME}' (a remote GPU/CPU "
                  "machine). Python state persists between run_python calls."),
)
client = LabClient(LAB_URL)


def _open_lab() -> str:
    try:
        r = httpx.post(f"{API}/api/v1/dsl/runtimes/{RID}/open", timeout=180).json()
    except Exception as e:
        return f"could not ask the backend to open the lab: {e}"
    return "" if r.get("ok") else (r.get("detail") or "lab open failed")


def _call(fn):
    """Run fn(); if the lab is not open, open it once and retry. Errors come back as text."""
    for attempt in (1, 2):
        try:
            return fn()
        except LabNotOpen:
            if attempt == 2 or not AUTO_OPEN:
                return ("ERROR: the DSLab lab for this runtime is not open. Open it from "
                        "Data Science Lab > Runtimes > Open Lab and try again.")
            err = _open_lab()
            if err:
                return f"ERROR: the lab was not open and re-opening it failed: {err}"
        except LabError as e:
            return f"ERROR: {e}"
        except Exception as e:  # never crash the MCP server
            return f"ERROR: {type(e).__name__}: {e}"


def _run_in_agent_kernel(code: str, timeout: int) -> str:
    kid = client.ensure_session(AGENT_SESSION, KERNEL)
    res = client.execute(kid, code, timeout=timeout)
    out = outputs_to_text(res["outputs"]) or "(no output)"
    head = {"ok": "", "error": "[execution error]\n",
            "timeout": f"[stopped after {timeout}s - kernel interrupted]\n"}.get(res["status"], "")
    return head + out


@server.tool()
def run_python(code: str, timeout_seconds: int = 120) -> str:
    """Execute Python code on the DSLab runtime in a persistent kernel and return its real output
    (stdout, results, errors). Variables and imports persist between calls. Use print() to show values."""
    return _call(lambda: _run_in_agent_kernel(code, timeout_seconds))


@server.tool()
def run_shell(command: str, timeout_seconds: int = 120) -> str:
    """Run a shell command on the DSLab runtime (e.g. 'nvidia-smi', 'pip list', 'ls -la') and
    return stdout, stderr and the exit code. Runs in the lab's working directory."""
    code = textwrap.dedent(f"""
        import subprocess as _sp
        _r = _sp.run({command!r}, shell=True, capture_output=True, text=True, timeout={int(timeout_seconds)})
        print(_r.stdout, end="")
        if _r.stderr: print("[stderr]\\n" + _r.stderr, end="")
        print(f"\\n[exit code {{_r.returncode}}]")
    """)
    return _call(lambda: _run_in_agent_kernel(code, timeout_seconds + 15))


@server.tool()
def runtime_info() -> str:
    """Describe the DSLab runtime: hostname, Python version, working directory and GPUs."""
    code = textwrap.dedent("""
        import os, platform, socket, subprocess, sys
        print("host:", socket.gethostname())
        print("python:", sys.version.split()[0], sys.executable)
        print("cwd:", os.getcwd())
        try:
            print(subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,utilization.gpu",
                                  "--format=csv"], capture_output=True, text=True, timeout=20).stdout or "no GPU info")
        except Exception as e:
            print("nvidia-smi not available:", e)
    """)
    return _call(lambda: _run_in_agent_kernel(code, 60))


@server.tool()
def list_files(path: str = "") -> str:
    """List files and folders in the lab workspace ('' = the workspace root)."""
    def go():
        rows = client.list_dir(path)
        if not rows:
            return "(empty directory)"
        return "\n".join(f"{'[dir] ' if r['type'] == 'directory' else '      '}{r['path']}"
                         + (f"  ({r.get('size')} bytes)" if r.get("size") is not None else "")
                         for r in rows)
    return _call(go)


@server.tool()
def read_file(path: str) -> str:
    """Read a text file or notebook from the lab workspace. Notebooks are shown cell by cell."""
    def go():
        d = client.get(path)
        if d.get("type") == "notebook":
            return _render_notebook(path, d["content"])
        if d.get("type") == "directory":
            return "ERROR: that path is a directory - use list_files"
        if d.get("format") == "base64":
            return f"(binary file, {d.get('size')} bytes - not shown)"
        text = d.get("content") or ""
        return text if len(text) < 20000 else text[:20000] + "\n... [truncated]"
    return _call(go)


@server.tool()
def write_file(path: str, content: str) -> str:
    """Create or overwrite a text file (e.g. a .py script or .csv) in the lab workspace."""
    return _call(lambda: f"saved {client.put_text(path, content)['path']}")


def _render_notebook(path: str, nb: dict) -> str:
    lines = [f"notebook {path}: {len(nb.get('cells', []))} cells"]
    for i, c in enumerate(nb.get("cells", [])):
        src = c.get("source", "")
        src = "".join(src) if isinstance(src, list) else src
        lines.append(f"\n--- cell {i} [{c.get('cell_type')}] ---\n{src}")
        if c.get("cell_type") == "code" and c.get("outputs"):
            lines.append("[output]\n" + outputs_to_text(c["outputs"], limit=3000))
    text = "\n".join(lines)
    return text if len(text) < 25000 else text[:25000] + "\n... [truncated]"


def _new_notebook() -> dict:
    return {"cells": [], "metadata": {"kernelspec": {"name": KERNEL, "display_name": KERNEL,
                                                    "language": "python"}},
            "nbformat": 4, "nbformat_minor": 5}


def _code_cell(src: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "id": os.urandom(4).hex(),
            "metadata": {}, "outputs": [], "source": src}


@server.tool()
def run_notebook(path: str, timeout_seconds: int = 900, stop_on_error: bool = True) -> str:
    """Execute every code cell of a notebook on the runtime in order, save the outputs into the
    notebook, and return a per-cell summary. Uses the notebook's own kernel (shared with JupyterLab)."""
    def go():
        d = client.get(path)
        if d.get("type") != "notebook":
            return "ERROR: not a notebook (.ipynb)"
        nb = d["content"]
        kid = client.ensure_session(path.strip("/"), KERNEL)
        summary, ran = [], 0
        for i, cell in enumerate(nb.get("cells", [])):
            if cell.get("cell_type") != "code":
                continue
            src = cell.get("source", "")
            src = "".join(src) if isinstance(src, list) else src
            if not src.strip():
                continue
            res = client.execute(kid, src, timeout=timeout_seconds)
            cell["outputs"], cell["execution_count"] = res["outputs"], res["execution_count"]
            ran += 1
            out = outputs_to_text(res["outputs"], limit=1500)
            summary.append(f"cell {i}: {res['status']}" + (f"\n{out}" if out else ""))
            if res["status"] != "ok" and stop_on_error:
                summary.append(f"stopped at cell {i} ({res['status']})")
                break
        client.put_notebook(path, nb)
        return f"ran {ran} code cell(s) in {path}; outputs saved.\n\n" + "\n\n".join(summary)
    return _call(go)


@server.tool()
def add_cell(path: str, source: str, execute: bool = True, cell_type: str = "code") -> str:
    """Append a cell to a notebook (created if missing). If execute is true and it is a code cell,
    run it in the notebook's kernel, store its output in the notebook and return the output."""
    def go():
        try:
            nb = client.get(path)["content"]
        except LabError:
            nb = _new_notebook()
        if cell_type == "markdown":
            cell = {"cell_type": "markdown", "id": os.urandom(4).hex(), "metadata": {}, "source": source}
        else:
            cell = _code_cell(source)
        nb.setdefault("cells", []).append(cell)
        msg = f"added cell {len(nb['cells']) - 1} to {path}"
        if execute and cell["cell_type"] == "code":
            kid = client.ensure_session(path.strip("/"), KERNEL)
            res = client.execute(kid, source, timeout=300)
            cell["outputs"], cell["execution_count"] = res["outputs"], res["execution_count"]
            msg += f"; executed ({res['status']})\n" + (outputs_to_text(res["outputs"]) or "(no output)")
        client.put_notebook(path, nb)
        return msg
    return _call(go)


@server.tool()
def restart_kernel() -> str:
    """Restart the agent's Python kernel on the runtime (clears all variables)."""
    def go():
        client.restart(client.ensure_session(AGENT_SESSION, KERNEL))
        return "kernel restarted"
    return _call(go)


# ------------------------------------------------------------------------------------------
# Background notebook jobs (long-running work such as fine-tuning).
#
# A job lives in <jupyter root>/<JOBS_DIR>/<job_id>/ on the runtime. start_notebook_job copies
# the Studio runner (app/finetune/remote_runner.py) there and launches it as a detached process
# group with the kernel's Python, so the work survives dropped tunnels, MCP calls and backend
# restarts. Progress is read from the job's status.json — cheap, no kernel round-trip.
# ------------------------------------------------------------------------------------------
import re as _re
from datetime import datetime as _dt, timezone as _tz
from pathlib import Path as _Path

JOBS_DIR = os.getenv("DSLAB_JOBS_DIR", "studio-jobs").strip("/") or "studio-jobs"
_JOB_ID = _re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_RUNNER_SRC = _Path(__file__).resolve().parents[1] / "finetune" / "remote_runner.py"
_STALE_HEARTBEAT_S = 90


def _job_dir(job_id: str) -> str:
    if not _JOB_ID.match(job_id or ""):
        raise LabError("invalid job_id (letters, digits, '_', '-', '.' only)")
    return f"{JOBS_DIR}/{job_id}"


def _safe_rel(name: str) -> str:
    parts = [p for p in (name or "").replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise LabError(f"invalid file name '{name}'")
    return "/".join(parts)


def _age_s(iso: str) -> float:
    try:
        return (_dt.now(_tz.utc) - _dt.fromisoformat(iso)).total_seconds()
    except Exception:
        return 1e9


@server.tool()
def stage_job_file(job_id: str, name: str, content: str, encoding: str = "text") -> str:
    """Write a file into a background job's directory on the runtime (creates the directory).
    encoding: 'text' for text/notebook JSON, 'base64' for binary data. Returns the saved path."""
    def go():
        jd = _job_dir(job_id)
        rel = _safe_rel(name)
        target = f"{jd}/{rel}"
        client.mkdirs(target.rsplit("/", 1)[0])
        if encoding == "base64":
            client.put_base64(target, content)
        else:
            client.put_text(target, content)
        return json.dumps({"ok": True, "path": target})
    return _call(go)


@server.tool()
def start_notebook_job(job_id: str, notebook: str = "notebook.ipynb", env: dict | None = None,
                       timeout_hours: float = 24.0, log_outputs_to_mlflow: bool = True,
                       mlflow_max_gb: float = 20.0) -> str:
    """Start a staged notebook as a detached background job on the runtime (survives disconnects).
    The notebook must already be in the job directory (stage_job_file). `env` is added to the job's
    environment (e.g. MLFLOW_TRACKING_URI, MLFLOW_RUN_ID). Poll with notebook_job_status."""
    def go():
        jd = _job_dir(job_id)
        nb = _safe_rel(notebook)
        if not client.exists(f"{jd}/{nb}"):
            return json.dumps({"ok": False, "error": f"{jd}/{nb} not found - stage it first"})
        client.put_text(f"{jd}/studio_runner.py", _RUNNER_SRC.read_text())
        safe_env = {str(k): str(v) for k, v in (env or {}).items()}
        code = textwrap.dedent(f"""
            import json as _j, os as _o, subprocess as _sp, sys as _s
            _jd = _o.path.abspath({jd!r})
            _pid = _o.path.join(_jd, "job.pid")
            def _alive(_pid):
                # kill(pid, 0) also succeeds for zombies: reap our own child, check /proc state
                try:
                    _o.waitpid(_pid, _o.WNOHANG)
                except Exception:
                    pass
                try:
                    _o.kill(_pid, 0)
                except Exception:
                    return False
                try:
                    return open("/proc/%d/stat" % _pid).read().rsplit(")", 1)[1].split()[0] != "Z"
                except Exception:
                    return True
            _running = False
            if _o.path.exists(_pid):
                try:
                    _running = _alive(int(open(_pid).read().strip()))
                except Exception:
                    _running = False
            if _running:
                print(_j.dumps({{"ok": False, "error": "job is already running",
                                 "pid": int(open(_pid).read().strip())}}))
            else:
                for _f in ("status.json", "outputs_manifest.json"):
                    try: _o.remove(_o.path.join(_jd, _f))
                    except FileNotFoundError: pass
                _env = dict(_o.environ); _env.update({safe_env!r})
                _env["PYTHONUNBUFFERED"] = "1"
                _out = open(_o.path.join(_jd, "runner.out"), "ab")
                _p = _sp.Popen([_s.executable, "-u", "studio_runner.py", "--notebook", {nb!r},
                                "--output-notebook", "executed.ipynb",
                                "--timeout-hours", str({float(timeout_hours)!r}),
                                "--log-outputs-to-mlflow", str({int(bool(log_outputs_to_mlflow))}),
                                "--mlflow-max-gb", str({float(mlflow_max_gb)!r})],
                               cwd=_jd, env=_env, stdout=_out, stderr=_sp.STDOUT,
                               stdin=_sp.DEVNULL, start_new_session=True)
                open(_pid, "w").write(str(_p.pid))
                import threading as _th
                _th.Thread(target=_p.wait, daemon=True).start()   # reap on exit (no zombie)
                print(_j.dumps({{"ok": True, "pid": _p.pid, "job_dir": _jd, "python": _s.executable}}))
        """)
        out = _run_in_agent_kernel(code, 60)
        line = next((ln for ln in reversed(out.splitlines()) if ln.strip().startswith("{")), "")
        return line or json.dumps({"ok": False, "error": out[-2000:]})
    return _call(go)


def _pid_alive(job_id: str) -> dict:
    jd = _job_dir(job_id)
    code = textwrap.dedent(f"""
        import json as _j, os as _o
        def _alive(_pid):
            # kill(pid, 0) also succeeds for zombies: reap our own child, check /proc state
            try:
                _o.waitpid(_pid, _o.WNOHANG)
            except Exception:
                pass
            try:
                _o.kill(_pid, 0)
            except Exception:
                return False
            try:
                return open("/proc/%d/stat" % _pid).read().rsplit(")", 1)[1].split()[0] != "Z"
            except Exception:
                return True
        _p = _o.path.join(_o.path.abspath({jd!r}), "job.pid")
        try:
            _pid = int(open(_p).read().strip())
            print(_j.dumps({{"alive": _alive(_pid), "pid": _pid}}))
        except Exception as _e:
            print(_j.dumps({{"alive": False, "detail": str(_e)}}))
    """)
    out = _run_in_agent_kernel(code, 30)
    line = next((ln for ln in reversed(out.splitlines()) if ln.strip().startswith("{")), "{}")
    try:
        return json.loads(line)
    except Exception:
        return {"alive": None, "detail": out[-300:]}


@server.tool()
def notebook_job_status(job_id: str) -> str:
    """Status of a background notebook job: state (starting|running|finalizing|completed|failed|
    cancelled|timeout|lost), current cell, progress bars, custom progress values and a log tail."""
    def go():
        jd = _job_dir(job_id)
        try:
            st = json.loads(client.read_text(f"{jd}/status.json") or "{}")
        except LabError as e:
            if "HTTP 404" not in str(e):
                raise
            st = {"state": "starting", "detail": "status.json not written yet"}
            try:
                st["runner_out"] = client.read_text(f"{jd}/runner.out")[-3000:]
            except LabError:
                pass
            if not client.exists(f"{jd}/job.pid"):
                st["state"] = "not_found"
                return json.dumps(st)
            # the runner died before it could write a status (e.g. bad interpreter)
            if st.get("runner_out") and not _pid_alive(job_id).get("alive", True):
                st["state"] = "lost"
            return json.dumps(st)
        if st.get("state") in ("starting", "running", "finalizing") \
                and _age_s(st.get("heartbeat", "")) > _STALE_HEARTBEAT_S:
            alive = _pid_alive(job_id)
            if alive.get("alive") is False:
                st["state"] = "lost"
                st["error"] = ("the job process is gone without a final status (machine restart, "
                               "OOM kill or manual kill)")
                try:
                    st["runner_out"] = client.read_text(f"{jd}/runner.out")[-3000:]
                except LabError:
                    pass
        return json.dumps(st)
    return _call(go)


@server.tool()
def cancel_notebook_job(job_id: str, grace_seconds: int = 20) -> str:
    """Stop a background notebook job (SIGTERM to its process group, SIGKILL after grace_seconds)."""
    def go():
        jd = _job_dir(job_id)
        code = textwrap.dedent(f"""
            import json as _j, os as _o, signal as _sg, time as _t
            _p = _o.path.join(_o.path.abspath({jd!r}), "job.pid")
            try:
                _pid = int(open(_p).read().strip())
            except Exception as _e:
                print(_j.dumps({{"ok": False, "error": "no pid file: " + str(_e)}})); raise SystemExit
            def _alive(_pid):
                # kill(pid, 0) also succeeds for zombies: reap our own child, check /proc state
                try:
                    _o.waitpid(_pid, _o.WNOHANG)
                except Exception:
                    pass
                try:
                    _o.kill(_pid, 0)
                except Exception:
                    return False
                try:
                    return open("/proc/%d/stat" % _pid).read().rsplit(")", 1)[1].split()[0] != "Z"
                except Exception:
                    return True
            if not _alive(_pid):
                print(_j.dumps({{"ok": True, "detail": "job was not running"}}))
            else:
                try: _o.killpg(_o.getpgid(_pid), _sg.SIGTERM)
                except Exception: _o.kill(_pid, _sg.SIGTERM)
                _d = _t.time() + {int(grace_seconds)}
                while _alive(_pid) and _t.time() < _d: _t.sleep(0.5)
                if _alive(_pid):
                    try: _o.killpg(_o.getpgid(_pid), _sg.SIGKILL)
                    except Exception: _o.kill(_pid, _sg.SIGKILL)
                print(_j.dumps({{"ok": True, "detail": "stopped", "pid": _pid}}))
        """)
        out = _run_in_agent_kernel(code, int(grace_seconds) + 30)
        line = next((ln for ln in reversed(out.splitlines()) if ln.strip().startswith("{")), "")
        return line or json.dumps({"ok": False, "error": out[-1000:]})
    return _call(go)


@server.tool()
def list_job_outputs(job_id: str) -> str:
    """Files a background job produced under its outputs/ folder (path, size, sha256), plus the
    job directory's own files (executed notebook, log, status)."""
    def go():
        jd = _job_dir(job_id)
        out: dict = {"job_dir": jd}
        try:
            out["manifest"] = json.loads(client.read_text(f"{jd}/outputs_manifest.json") or "{}")
        except LabError:
            out["manifest"] = None
        try:
            out["job_files"] = [{"name": r["name"], "type": r["type"], "size": r.get("size")}
                                for r in client.list_dir(jd)]
        except LabError as e:
            out["job_files"] = []
            out["error"] = str(e)
        return json.dumps(out)
    return _call(go)


if __name__ == "__main__":
    server.run(transport="stdio")
