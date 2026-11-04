"""Adapt tcs_decision_framework_model_tuning.html into a native TCS Domain AI Studio module.

Outputs (frontend/src/screens/domainai/dfm/):
  engine.ts  - the original script, business logic VERBATIM, wrapped in createDfmEngine(root, host)
  markup.ts  - the original <body> markup (brand block removed; inline handlers namespaced)
  dfm.css    - the original stylesheet scoped under .dfm-root and mapped onto platform tokens

Only page-level concerns are changed:
  * global DOM access   -> the module root   (shadowed `document` inside the factory)
  * localStorage        -> host.storage      (platform backend persistence)
  * alert / confirm     -> host.notify / host.confirm (platform toasts / dialog)
  * DOMContentLoaded    -> engine.boot()     (platform screen mount)
  * inline onclick="f()"-> onclick="__dfm.f()"  (no global function names)
  * CSS custom props    -> --dfm-*  (no clash with platform --accent etc.)
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

SRC = Path(sys.argv[1])
OUT = Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
log = []

s = SRC.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
css = s[s.index("<style>") + 7:s.index("</style>")]
body = s[s.index("<body>") + 6:s.index("<script>")]
js = s[s.index("<script>") + 8:s.index("</script>")]

FUNCS = re.findall(r"(?m)^\s*(?:async\s+)?function\s+([A-Za-z0-9_]+)", js)
VARS = sorted(set(re.findall(r"--([a-z0-9-]+)\s*:", css[:css.index("}")])), key=len, reverse=True)
log.append(f"{len(FUNCS)} functions, {len(VARS)} css variables")


# ------------------------------------------------------------------ shared helpers
def rename_vars(text: str) -> str:
    for v in VARS:
        text = re.sub(r"var\(--" + re.escape(v) + r"\)", f"var(--dfm-{v})", text)
        text = re.sub(r"(['\"])--" + re.escape(v) + r"\1", r"\1--dfm-" + v + r"\1", text)
    text = text.replace("var(--${", "var(--dfm-${")
    return text


FN_RE = re.compile(r"(?<![\w.$])(" + "|".join(map(re.escape, sorted(FUNCS, key=len, reverse=True))) + r")\s*\(")


def ns_handler(value: str) -> str:
    """Prefix module function calls with __dfm. - but never inside ${...} template expressions."""
    out, i = [], 0
    while i < len(value):
        j = value.find("${", i)
        if j < 0:
            out.append(FN_RE.sub(r"__dfm.\1(", value[i:]))
            break
        out.append(FN_RE.sub(r"__dfm.\1(", value[i:j]))
        depth, k = 0, j + 1
        while k < len(value):
            if value[k] == "{":
                depth += 1
            elif value[k] == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        out.append(value[j:k + 1])
        i = k + 1
    return "".join(out)


HANDLER_RE = re.compile(r'(on(?:click|change|input|submit|keyup|keydown|blur|focus))="([^"]*)"')


def ns_handlers(text: str) -> tuple[str, int]:
    n = 0

    def rep(m):
        nonlocal n
        new = ns_handler(m.group(2))
        n += new != m.group(2)
        return f'{m.group(1)}="{new}"'
    return HANDLER_RE.sub(rep, text), n


# ------------------------------------------------------------------ markup
def remove_div(html: str, cls: str) -> str:
    i = html.index(f'<div class="{cls}">')
    depth, k = 0, i
    for m in re.finditer(r"<div\b|</div>", html[i:]):
        depth += 1 if m.group(0) == "<div" else -1
        if depth == 0:
            k = i + m.end()
            break
    return html[:i] + html[k:]


markup = remove_div(body, "brand")          # platform header already carries the brand
markup, nh = ns_handlers(markup)
markup = rename_vars(markup)
markup = re.sub(r"<!--.*?-->", "", markup, flags=re.S).strip()
log.append(f"markup: brand block removed, {nh} inline handlers namespaced")
(OUT / "markup.ts").write_text(
    "// AUTO-ADAPTED from tcs_decision_framework_model_tuning.html (body markup). Do not edit by hand.\n"
    f"export const DFM_MARKUP = {json.dumps(markup, ensure_ascii=False)};\n", encoding="utf-8")

# ------------------------------------------------------------------ engine
ejs = js
ejs, nh = ns_handlers(ejs)
log.append(f"engine: {nh} template handlers namespaced")
ejs = rename_vars(ejs)

HEX = {"#3b82f6": "#76b900", "#f97316": "#f0a83c", "#e5e9f2": "#eefdf0", "#6b7691": "#8fae97",
       "#424b66": "#48594c", "#10b981": "#34d399", "#ef4444": "#ff5c5c", "#8b5cf6": "#9d7bff"}
for a, b in HEX.items():
    ejs = re.sub(re.escape(a), b, ejs, flags=re.I)

# confirm() becomes the platform dialog (async) - the only control-flow edit
old = "function resetAssessment() {\n"
assert ejs.count(old) == 1
ejs = ejs.replace(old, "async function resetAssessment() {\n")
old = "if (!confirm("
assert ejs.count(old) == 1
ejs = ejs.replace(old, "if (!(await confirm(")
ejs = re.sub(r"if \(!\(await confirm\((.*?)\)\)\s*return;",
             lambda m: f"if (!(await confirm({m.group(1)}))) return;", ejs, count=1)

# DOMContentLoaded bootstrap -> engine.boot()
i = ejs.index("window.addEventListener('DOMContentLoaded'")
k = ejs.index("});", i) + 3
init_body = ejs[i:k]
ejs = ejs[:i] + "/* DOMContentLoaded bootstrap moved to __boot() */" + ejs[k:]
log.append("engine: DOMContentLoaded -> boot(), confirm -> async platform dialog")

def indent(t, n=4):
    return "\n".join((" " * n + ln) if ln.strip() else ln for ln in t.split("\n"))

engine = f'''// @ts-nocheck
/* AUTO-ADAPTED from tcs_decision_framework_model_tuning.html (Decision Framework for Model
   Tuning v3). The framework data and every function below are the ORIGINAL code, unchanged,
   except: CSS variable names (--dfm-*), theme colours, namespaced inline handlers, and
   resetAssessment awaiting the platform confirm dialog. Page access is redirected here: */
export function createDfmEngine(root, host) {{
    const document = {{
        getElementById: (id) => root.querySelector('#' + CSS.escape(id)),
        querySelector: (sel) => root.querySelector(sel),
        querySelectorAll: (sel) => root.querySelectorAll(sel),
        createElement: (tag) => window.document.createElement(tag),
        execCommand: (...a) => window.document.execCommand(...a),
        get body() {{ return window.document.body; }},
    }};
    const localStorage = host.storage;
    const alert = (msg) => host.notify(String(msg));
    const confirm = (msg) => host.confirm(String(msg));

{indent(ejs.strip())}

    /* ---------------- host bridge (additive; reuses the original functions) ---------------- */
    function __showActions(on) {{
        ['btn-export', 'btn-reset'].forEach(id => {{
            const el = document.getElementById(id);
            if (el) el.style.display = on ? 'inline-flex' : 'none';
        }});
    }}
    function __boot() {{   // original DOMContentLoaded body
        loadState();
        if (STATE.meta && STATE.meta.startedAt) {{
            __showActions(true);
        }}
    }}
    function __open(state) {{
        STATE = state;
        __showActions(true);
        switchMode('assess');
    }}
    function __close() {{
        STATE = {{
            meta: {{ assessmentName: '', client: '', industry: '', leadConsultant: '', startedAt: null, lastUpdatedAt: null, frameworkVersion: 'v3.0' }},
            answers: {{}}, notes: {{}}, verdicts: {{}}, rationales: {{}},
            currentGate: null
        }};
        __showActions(false);
        switchMode('doc');
    }}
    const __LABELS = {{ pass: 'Ready', fail: 'Needs Work', pending: 'In Discussion', 'in-progress': 'In Progress' }};
    function __answered(v) {{
        return !(v === undefined || v === null || v === '' || (Array.isArray(v) && v.length === 0));
    }}
    function __summary() {{
        const overall = computeOverallVerdict();
        let total = 0, answered = 0;
        FRAMEWORK.forEach(g => g.dimensions.forEach(d => d.questions.forEach(q => {{
            total++;
            if (__answered(STATE.answers[q.id])) answered++;
        }})));
        const gates = FRAMEWORK.map(g => computeGateVerdict(g));
        return {{
            overall, overall_label: overall ? __LABELS[overall] : 'Not started',
            answered, total_questions: total,
            gates_decided: gates.filter(v => v && v !== 'in-progress').length,
            gates_total: FRAMEWORK.length,
        }};
    }}
    function __reportModel() {{
        const overall = computeOverallVerdict();
        const tmp = window.document.createElement('div');
        tmp.innerHTML = renderNextSteps(overall) || '';
        let nextSteps = Array.from(tmp.querySelectorAll('li')).map(li => li.textContent.trim()).filter(Boolean);
        if (!nextSteps.length && tmp.textContent.trim()) nextSteps = [tmp.textContent.trim()];
        return {{
            meta: STATE.meta,
            overall, overall_label: formatVerdict(overall),
            summary: __summary(),
            next_steps: nextSteps,
            gates: FRAMEWORK.map(g => ({{
                id: g.id, num: g.num, title: g.title, deliverable: g.deliverable || '',
                verdict: computeGateVerdict(g), verdict_label: __LABELS[computeGateVerdict(g)] || 'Not started',
                dimensions: g.dimensions.map(d => ({{
                    id: d.id, tag: d.tag, title: d.title,
                    verdict: STATE.verdicts[d.id] || null,
                    verdict_label: __LABELS[STATE.verdicts[d.id]] || 'Not set',
                    rationale: STATE.rationales[d.id] || '',
                    notes: STATE.notes[d.id] || '',
                    questions: d.questions.map(q => ({{ id: q.id, text: q.text, answer: formatAnswer(q.id) }})),
                }})),
            }})),
        }};
    }}

    return {{
        boot: __boot, open: __open, close: __close,
        getState: () => STATE, summary: __summary, reportModel: __reportModel,
        generateLlmPrompt,
        handlers: {{ {", ".join(FUNCS)} }},
    }};
}}
'''
(OUT / "engine.ts").write_text(engine, encoding="utf-8")

# ------------------------------------------------------------------ css
css_nc = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

PLATFORM_VARS = {
    "bg": "var(--app-bg)", "bg-deep": "#080b09", "bg-elevated": "var(--panel)",
    "surface": "var(--panel)", "surface-2": "var(--raised)", "surface-3": "#223027", "surface-4": "#2c3d31",
    "border": "var(--border)", "border-light": "#3a4f3f",
    "tcs": "var(--accent)", "tcs-bright": "var(--accent-2)", "tcs-glow": "rgba(118, 185, 0, 0.15)",
    "tcs-deep": "var(--accent-dim)",
    "accent": "var(--warning)", "accent-glow": "rgba(240, 168, 60, 0.15)",
    "ready": "#34d399", "ready-glow": "rgba(52, 211, 153, 0.15)",
    "needswork": "var(--danger)", "needswork-glow": "rgba(255, 92, 92, 0.15)",
    "discussion": "var(--warning)", "discussion-glow": "rgba(240, 168, 60, 0.15)",
    "pass": "#34d399", "pass-glow": "rgba(52, 211, 153, 0.15)",
    "fail": "var(--danger)", "fail-glow": "rgba(255, 92, 92, 0.15)",
    "pending": "var(--warning)", "pending-glow": "rgba(240, 168, 60, 0.15)",
    "c-amber": "var(--warning)", "c-violet": "var(--violet)", "c-cyan": "#22c3d6", "c-rose": "#ec4899",
    "c-emerald": "#34d399",
    "text": "var(--text)", "text-bright": "#ffffff", "text-dim": "var(--muted)",
    "text-muted": "#6f8a76", "text-faint": "#48594c",
}
missing = [v for v in VARS if v not in PLATFORM_VARS]
assert not missing, f"unmapped module variables: {missing}"

RGBA = {(59, 130, 246): (118, 185, 0), (37, 99, 235): (118, 185, 0), (30, 64, 175): (79, 122, 0),
        (249, 115, 22): (240, 168, 60), (10, 13, 20): (11, 15, 12), (6, 8, 13): (8, 11, 9),
        (14, 18, 32): (18, 24, 20), (19, 24, 41): (20, 26, 22), (26, 32, 54): (27, 35, 29),
        (16, 185, 129): (52, 211, 153), (239, 68, 68): (255, 92, 92), (245, 158, 11): (240, 168, 60)}
seen_rgba = Counter()


def map_rgba(m):
    r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
    seen_rgba[(r, g, b)] += 1
    nr, ng, nb = RGBA.get((r, g, b), (r, g, b))
    return f"rgba({nr}, {ng}, {nb}, {m.group(4)})"


def map_value(v: str) -> str:
    v = rename_vars(v)
    v = re.sub(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)", map_rgba, v)
    v = re.sub(r"'Syne',\s*sans-serif|'Instrument Serif',\s*serif", "var(--dfm-font-display)", v)
    v = re.sub(r"'Inter',\s*(-apple-system,\s*)?sans-serif", "var(--dfm-font)", v)
    v = re.sub(r"'JetBrains Mono',\s*monospace", "var(--mono)", v)
    v = v.replace("100vh", "var(--dfm-vh, 100vh)")
    v = re.sub(r"\bfadeIn\b", "dfm-fadeIn", v)
    for a, b in {"#ea580c": "#d9932f", "#0f1430": "#141a16"}.items():
        v = v.replace(a, b)

    def fs(m):  # compress display sizes to the platform's typographic scale
        n = float(m.group(1))
        return f"font-size: {round(24 + (n - 24) * 0.35)}px" if n > 26 else m.group(0)
    v = re.sub(r"font-size:\s*([\d.]+)px", fs, v)
    v = re.sub(r"letter-spacing:\s*-(\d+(?:\.\d+)?)px",
               lambda m: f"letter-spacing: -{min(float(m.group(1)), 0.6)}px", v)
    return v


def split_sel(prelude: str) -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in prelude:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip()); cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def scope(prelude: str) -> str | None:
    sels = []
    for sel in split_sel(prelude):
        if sel == "html":
            continue
        if sel in (":root", "body"):
            sels.append(".dfm-root")
        elif sel == "*":
            sels.append(".dfm-root *")
        elif sel.startswith("::"):
            sels.append(".dfm-root " + sel)
        elif sel.startswith("body "):
            sels.append(".dfm-root " + sel[5:])
        else:
            sels.append(".dfm-root " + sel)
    return ", ".join(sels) if sels else None


def parse_rules(text: str):
    i, n = 0, len(text)
    while i < n:
        j = text.find("{", i)
        if j < 0:
            break
        prelude = text[i:j].strip()
        depth, k = 0, j
        while k < n:
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        yield prelude, text[j + 1:k]
        i = k + 1


out_rules: list[str] = []
root_done = False


def emit(prelude, block, indent_=""):
    global root_done
    if prelude == ":root" and not root_done:
        root_done = True
        decls = "\n".join(f"{indent_}    --dfm-{k}: {v};" for k, v in PLATFORM_VARS.items())
        return (f"{indent_}.dfm-root {{\n{decls}\n"
                f"{indent_}    --dfm-font: Inter, -apple-system, \"Segoe UI\", Roboto, sans-serif;\n"
                f"{indent_}    --dfm-font-display: Inter, -apple-system, \"Segoe UI\", Roboto, sans-serif;\n"
                f"{indent_}}}")
    sel = scope(prelude)
    if not sel:
        return ""
    body_ = "\n".join(f"{indent_}    {d.strip()};" for d in map_value(block).split(";") if d.strip())
    return f"{indent_}{sel} {{\n{body_}\n{indent_}}}"


container_queries = 0
for prelude, block in parse_rules(css_nc):
    if prelude.startswith("@keyframes"):
        out_rules.append(prelude.replace("fadeIn", "dfm-fadeIn") + " {" + map_value(block) + "}")
    elif prelude.startswith("@media print"):
        inner = "\n".join(filter(None, (emit(p, b, "    ") for p, b in parse_rules(block))))
        out_rules.append("@media print {\n" + inner + "\n}")
    elif prelude.startswith("@media"):
        cond = prelude[len("@media"):].strip()
        inner = "\n".join(filter(None, (emit(p, b, "    ") for p, b in parse_rules(block))))
        out_rules.append(f"@container dfm {cond} {{\n{inner}\n}}")   # module width, not viewport
        container_queries += 1
    else:
        r = emit(prelude, block)
        if r:
            out_rules.append(r)

log.append(f"css: {len(out_rules)} rules scoped, {container_queries} media->container queries, "
           f"rgba seen {dict(seen_rgba)}")

PLATFORM_LAYER = r"""
/* =====================================================================================
   PLATFORM INTEGRATION LAYER - fits the module into the TCS Domain AI Studio shell and
   aligns it with platform components (Blueprint buttons/tabs, section headers, spacing).
   ===================================================================================== */
.dfm-root {
    container-type: inline-size;
    container-name: dfm;
    font-family: var(--dfm-font);
    margin: 0 -22px -18px;              /* full-bleed inside .main-pane padding */
    min-height: var(--dfm-vh, 100vh);
    overflow-x: clip;
    isolation: isolate;                 /* module z-indexes never compete with platform overlays */
}
.dfm-root .app-header {
    background: rgba(20, 26, 22, 0.94);
    padding: 10px 22px;
    gap: 16px;
    min-height: 52px;
}
.dfm-root .mode-switch { background: transparent; border: none; padding: 0; gap: 4px; }
.dfm-root .mode-btn {
    font-family: var(--dfm-font); font-size: 13px; font-weight: 600; letter-spacing: 0;
    text-transform: none; color: var(--muted); border-radius: 0; padding: 8px 4px; margin-right: 14px;
    border-bottom: 2px solid transparent; background: transparent;
}
.dfm-root .mode-btn:hover { color: var(--text); background: transparent; }
.dfm-root .mode-btn.active { color: var(--accent); background: transparent; border-bottom-color: var(--accent);
    box-shadow: none; }
.dfm-root .btn {
    font-family: var(--dfm-font); font-size: 13px; font-weight: 500; letter-spacing: 0; text-transform: none;
    border-radius: 4px; padding: 6px 12px; min-height: 30px; background: var(--raised);
    border: 1px solid var(--border); color: var(--text);
}
.dfm-root .btn:hover { border-color: var(--accent-dim); background: #223027; }
.dfm-root .btn-primary { background: var(--accent); border-color: var(--accent); color: #0b0f0c; font-weight: 600; }
.dfm-root .btn-primary:hover { background: var(--accent-2); border-color: var(--accent-2); color: #0b0f0c; }
.dfm-root .btn-orange { background: transparent; border-color: rgba(255, 92, 92, 0.55); color: var(--danger); }
.dfm-root .btn-orange:hover { background: rgba(255, 92, 92, 0.1); border-color: var(--danger); }
.dfm-root input, .dfm-root select, .dfm-root textarea { font-family: var(--dfm-font); }
.dfm-root .doc-hero h1 em, .dfm-root h2 em, .dfm-root h3 em { font-style: normal; color: var(--accent); }
.dfm-root .tcs-mark { display: none; }
/* hero: the decorative glow sat in normal flow (600px) and pushed the title below the fold */
.dfm-root .doc-hero-glow { position: absolute; top: -160px; left: -80px; pointer-events: none; z-index: 0; }
.dfm-root .doc-hero > *:not(.doc-hero-glow) { position: relative; z-index: 1; }
/* one content gutter, aligned with the platform page-header title */
.dfm-root .app-header { padding-left: 13px; padding-right: 22px; }
.dfm-root .doc-hero { padding: 32px 40px 40px; }
.dfm-root .doc-content { padding: 8px 40px 48px; max-width: none; }
.dfm-root .doc-section { margin-top: 44px; }
.dfm-root .doc-section:first-child { margin-top: 32px; }
.dfm-root .workspace { padding: 28px 32px; }
.dfm-root .doc-hero-cta .btn { font-size: 13px; padding: 8px 16px; letter-spacing: 0; }
.dfm-root .doc-hero h1 em, .dfm-root .doc-section-head h2 em, .dfm-root .doc-section-head h3 em {
    font-style: normal; background: none; -webkit-text-fill-color: currentColor; color: var(--accent); }

/* print: only the module's report, never the platform chrome */
@media print {
    body:has(.dfm-root) .bp5-navbar,
    body:has(.dfm-root) .nav-rail,
    body:has(.dfm-root) .app-footer,
    body:has(.dfm-root) .dfm-pagehead { display: none !important; }
    body:has(.dfm-root) .app-shell, body:has(.dfm-root) .app-body,
    body:has(.dfm-root) .main-pane { display: block !important; overflow: visible !important;
        height: auto !important; padding: 0 !important; background: #fff !important; }
    .dfm-root { margin: 0 !important; min-height: 0 !important; background: #fff !important; color: #000 !important; }
}
"""
(OUT / "dfm.css").write_text(
    "/* AUTO-ADAPTED from tcs_decision_framework_model_tuning.html - module styles scoped to .dfm-root\n"
    "   and mapped onto TCS Domain AI Studio tokens. Do not edit by hand; regenerate. */\n"
    + "\n\n".join(out_rules) + "\n" + PLATFORM_LAYER, encoding="utf-8")

# report class-name collisions with platform global classes
mod_classes = set(re.findall(r'class="([^"]+)"', markup + js))
mod_classes = {c for cl in mod_classes for c in cl.split() if "$" not in c}
print("\n".join(log))
print("module classes:", len(mod_classes))
json.dump(sorted(mod_classes), open("/tmp/dfm_classes.json", "w"))
