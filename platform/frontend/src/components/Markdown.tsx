// Dependency-free markdown -> React renderer. Handles headings, bold/italic,
// inline code, fenced code blocks, ordered/unordered lists, blockquotes, links,
// horizontal rules, and paragraphs — enough for clean, readable agent output.
import React from "react";

function inline(text: string, key: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const parts = text.split(/(`[^`]+`)/g);
  parts.forEach((tok, i) => {
    if (tok.startsWith("`") && tok.endsWith("`")) {
      out.push(<code key={`${key}-c${i}`} className="md-code">{tok.slice(1, -1)}</code>);
      return;
    }
    const linkRe = /\[([^\]]+)\]\(([^)]+)\)/g;
    let last = 0, m: RegExpExecArray | null, seg = 0;
    const pushStyled = (s: string, k: string) => {
      const bparts = s.split(/(\*\*[^*]+\*\*)/g);
      bparts.forEach((bp, bi) => {
        if (bp.startsWith("**") && bp.endsWith("**")) {
          out.push(<strong key={`${key}-b${k}-${bi}`}>{bp.slice(2, -2)}</strong>);
        } else {
          const iparts = bp.split(/(\*[^*]+\*|_[^_]+_)/g);
          iparts.forEach((ip, ii) => {
            if ((ip.startsWith("*") && ip.endsWith("*")) || (ip.startsWith("_") && ip.endsWith("_"))) {
              out.push(<em key={`${key}-i${k}-${bi}-${ii}`}>{ip.slice(1, -1)}</em>);
            } else if (ip) {
              out.push(<span key={`${key}-t${k}-${bi}-${ii}`}>{ip}</span>);
            }
          });
        }
      });
    };
    while ((m = linkRe.exec(tok)) !== null) {
      if (m.index > last) pushStyled(tok.slice(last, m.index), `${i}-${seg++}`);
      out.push(<a key={`${key}-l${i}-${seg}`} href={m[2]} target="_blank" rel="noreferrer">{m[1]}</a>);
      last = linkRe.lastIndex;
    }
    if (last < tok.length) pushStyled(tok.slice(last), `${i}-${seg++}`);
  });
  return out;
}

export function Markdown({ text }: { text: string }) {
  const lines = (text || "").replace(/\r\n/g, "\n").split("\n");
  const out: React.ReactNode[] = [];
  let ul: React.ReactNode[] = [];
  let ol: React.ReactNode[] = [];
  let para: string[] = [];
  let inCode = false, codeLang = "", code: string[] = [];

  const flushPara = () => {
    if (para.length) { out.push(<p key={`p${out.length}`} className="md-p">{inline(para.join(" "), `p${out.length}`)}</p>); para = []; }
  };
  const flushUl = () => { if (ul.length) { out.push(<ul key={`ul${out.length}`} className="md-ul">{ul}</ul>); ul = []; } };
  const flushOl = () => { if (ol.length) { out.push(<ol key={`ol${out.length}`} className="md-ol">{ol}</ol>); ol = []; } };
  const flushAll = () => { flushPara(); flushUl(); flushOl(); };

  lines.forEach((raw, i) => {
    const ln = raw;
    if (/^\s*```/.test(ln)) {
      if (!inCode) { flushAll(); inCode = true; codeLang = ln.replace(/^\s*```/, "").trim(); code = []; }
      else { out.push(<pre key={`pre${out.length}`} className="md-pre"><code data-lang={codeLang}>{code.join("\n")}</code></pre>); inCode = false; }
      return;
    }
    if (inCode) { code.push(ln); return; }

    if (!ln.trim()) { flushAll(); return; }
    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(ln)) { flushAll(); out.push(<hr key={`hr${out.length}`} className="md-hr" />); return; }

    const h = ln.match(/^(#{1,4})\s+(.*)$/);
    if (h) { flushAll(); const lvl = h[1].length; const Tag = (`h${Math.min(lvl + 1, 5)}`) as any;
      out.push(<Tag key={`h${out.length}`} className={`md-h md-h${lvl}`}>{inline(h[2], `h${out.length}`)}</Tag>); return; }

    if (/^\s*>\s?/.test(ln)) { flushPara(); flushUl(); flushOl();
      out.push(<blockquote key={`bq${out.length}`} className="md-bq">{inline(ln.replace(/^\s*>\s?/, ""), `bq${out.length}`)}</blockquote>); return; }

    if (/^\s*[-*]\s+/.test(ln)) { flushPara(); flushOl(); ul.push(<li key={i}>{inline(ln.replace(/^\s*[-*]\s+/, ""), `li${i}`)}</li>); return; }
    if (/^\s*\d+\.\s+/.test(ln)) { flushPara(); flushUl(); ol.push(<li key={i}>{inline(ln.replace(/^\s*\d+\.\s+/, ""), `li${i}`)}</li>); return; }

    para.push(ln.trim());
  });
  if (inCode && code.length) out.push(<pre key={`pre${out.length}`} className="md-pre"><code>{code.join("\n")}</code></pre>);
  flushAll();
  return <div className="md">{out}</div>;
}
