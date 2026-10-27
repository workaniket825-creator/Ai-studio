import { useEffect, useRef, useState } from "react";

/**
 * HelpBot — a tiny, shiny, techie robot that wanders down the right margin of the
 * Setup & Help section, hopping from one spot to another, waving, and dropping the
 * occasional friendly line. Pure decoration: it lives in the right gutter so it never
 * covers the text. Respects prefers-reduced-motion.
 */

const LINES = [
  "Need a hand? 🤖",
  "Psst… try step 2!",
  "You've got this!",
  "Copy-paste ready ✨",
  "Beep boop — let's go!",
  "Stuck? Ping the ⌄ arrows",
  "All open-source, promise!",
  "Almost there!",
];

export function HelpBot() {
  const [top, setTop] = useState(120);        // vertical position (px from top of section)
  const [walking, setWalking] = useState(false);
  const [facing, setFacing] = useState(1);    // 1 = right-ish, -1 = left-ish (subtle lean)
  const [jump, setJump] = useState(false);
  const [bubble, setBubble] = useState<string | null>(null);
  const reduced = useRef(false);

  useEffect(() => {
    reduced.current = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    if (reduced.current) return;

    let alive = true;
    const wander = () => {
      if (!alive) return;
      // pick a new vertical spot aligned roughly with the steps
      const min = 90, max = Math.max(min + 200, (document.querySelector(".help-scope")?.clientHeight || 700) - 140);
      const next = Math.round(min + Math.random() * (max - min));
      setFacing(next > top ? 1 : -1);
      setWalking(true);
      setTop(next);
      // little hop on arrival
      window.setTimeout(() => { if (alive) setJump(true); }, 900);
      window.setTimeout(() => { if (alive) { setJump(false); setWalking(false); } }, 1250);
      // schedule the next wander
      window.setTimeout(wander, 2600 + Math.random() * 2600);
    };
    const t0 = window.setTimeout(wander, 1400);

    // occasional speech bubble
    const bt = window.setInterval(() => {
      if (!alive) return;
      setBubble(LINES[Math.floor(Math.random() * LINES.length)]);
      window.setTimeout(() => alive && setBubble(null), 2600);
    }, 7000);

    return () => { alive = false; window.clearTimeout(t0); window.clearInterval(bt); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const wave = () => {
    setBubble(LINES[Math.floor(Math.random() * LINES.length)]);
    setJump(true);
    window.setTimeout(() => setJump(false), 380);
    window.setTimeout(() => setBubble(null), 2200);
  };

  return (
    <div aria-hidden style={{
      position: "absolute", right: -8, top, transition: "top 1.1s cubic-bezier(.5,.05,.3,1)",
      width: 64, zIndex: 5, pointerEvents: "auto", cursor: "pointer",
    }} onClick={wave} title="Hi! I'm here to help.">
      <style>{`
        @keyframes hb-bob { 0%,100%{ transform: translateY(0) } 50%{ transform: translateY(-4px) } }
        @keyframes hb-jump { 0%{ transform: translateY(0) scale(1,1) } 30%{ transform: translateY(2px) scale(1.1,.86) }
          60%{ transform: translateY(-16px) scale(.94,1.12) } 100%{ transform: translateY(0) scale(1,1) } }
        @keyframes hb-blink { 0%,92%,100%{ transform: scaleY(1) } 96%{ transform: scaleY(.1) } }
        @keyframes hb-antenna { 0%,100%{ opacity:.5; r:2 } 50%{ opacity:1; r:2.6 } }
        @keyframes hb-leg-l { 0%,100%{ transform: rotate(14deg) } 50%{ transform: rotate(-14deg) } }
        @keyframes hb-leg-r { 0%,100%{ transform: rotate(-14deg) } 50%{ transform: rotate(14deg) } }
        @keyframes hb-arm { 0%,100%{ transform: rotate(8deg) } 50%{ transform: rotate(-18deg) } }
        @keyframes hb-shadow { 0%,100%{ transform: scaleX(1); opacity:.35 } 50%{ transform: scaleX(.8); opacity:.2 } }
        @keyframes hb-bubble-in { from{ opacity:0; transform: translateY(4px) scale(.9) } to{ opacity:1; transform: none } }
        .hb-float { animation: hb-bob 2.4s ease-in-out infinite; }
        .hb-jumping { animation: hb-jump .5s cubic-bezier(.3,.7,.3,1); }
        .hb-eye { transform-box: fill-box; transform-origin: center; animation: hb-blink 4.2s infinite; }
        .hb-leg-l { transform-box: fill-box; transform-origin: top center; }
        .hb-leg-r { transform-box: fill-box; transform-origin: top center; }
        .hb-arm-l { transform-box: fill-box; transform-origin: top center; }
        .hb-walking .hb-leg-l { animation: hb-leg-l .34s linear infinite; }
        .hb-walking .hb-leg-r { animation: hb-leg-r .34s linear infinite; }
        .hb-walking .hb-arm-l { animation: hb-arm .34s linear infinite; }
        @media (prefers-reduced-motion: reduce) { .hb-float,.hb-jumping,.hb-eye,.hb-walking * { animation: none !important; } }
      `}</style>

      {bubble && (
        <div style={{
          position: "absolute", right: 52, top: 4, whiteSpace: "nowrap",
          background: "var(--panel, #10160f)", color: "var(--text, #dfeed2)",
          border: "1px solid var(--accent, #76B900)", borderRadius: 10, padding: "5px 10px",
          fontSize: 11, fontWeight: 600, boxShadow: "0 4px 18px rgba(118,185,0,.25)",
          animation: "hb-bubble-in .2s ease-out",
        }}>
          {bubble}
          <span style={{ position: "absolute", right: -5, top: 10, width: 8, height: 8,
            background: "var(--panel, #10160f)", borderRight: "1px solid var(--accent,#76B900)",
            borderTop: "1px solid var(--accent,#76B900)", transform: "rotate(45deg)" }} />
        </div>
      )}

      <div className={`hb-float ${walking ? "hb-walking" : ""}`}>
        <div className={jump ? "hb-jumping" : ""} style={{ transform: `scaleX(${facing})` }}>
          <svg width="64" height="64" viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <linearGradient id="hb-body" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="#e9f7d4" />
                <stop offset="0.5" stopColor="#b9dd86" />
                <stop offset="1" stopColor="#76B900" />
              </linearGradient>
              <radialGradient id="hb-eye" cx="0.5" cy="0.5" r="0.5">
                <stop offset="0" stopColor="#eafff6" />
                <stop offset="0.6" stopColor="#38e1ff" />
                <stop offset="1" stopColor="#0a97c9" />
              </radialGradient>
              <filter id="hb-glow" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="1.6" result="b" />
                <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
            </defs>

            {/* shadow */}
            <ellipse cx="32" cy="60" rx="13" ry="3" fill="#000"
              style={{ transformBox: "fill-box", transformOrigin: "center", animation: "hb-shadow 2.4s ease-in-out infinite" }} />

            {/* antenna */}
            <line x1="32" y1="12" x2="32" y2="6" stroke="#8fb85a" strokeWidth="1.6" />
            <circle cx="32" cy="5" r="2.2" fill="#8affd6"
              style={{ filter: "url(#hb-glow)", animation: "hb-antenna 1.4s ease-in-out infinite" }} />

            {/* legs */}
            <g className="hb-leg-l"><rect x="25" y="46" width="4.4" height="10" rx="2.2" fill="#5f8a2e" />
              <rect x="23.5" y="55" width="7.5" height="3.2" rx="1.6" fill="#40611c" /></g>
            <g className="hb-leg-r"><rect x="34.6" y="46" width="4.4" height="10" rx="2.2" fill="#5f8a2e" />
              <rect x="33" y="55" width="7.5" height="3.2" rx="1.6" fill="#40611c" /></g>

            {/* arms */}
            <g className="hb-arm-l"><rect x="12.5" y="28" width="4" height="12" rx="2" fill="#7fae42" /></g>
            <g><rect x="47.5" y="28" width="4" height="12" rx="2" fill="#7fae42" /></g>

            {/* body */}
            <rect x="18" y="27" width="28" height="22" rx="7" fill="url(#hb-body)"
              stroke="#3f5e1d" strokeWidth="1" />
            <rect x="23" y="33" width="18" height="8" rx="3" fill="#0d1b06" opacity="0.55" />
            <circle cx="27" cy="37" r="1.3" fill="#8affd6" />
            <circle cx="32" cy="37" r="1.3" fill="#ffd166" />
            <circle cx="37" cy="37" r="1.3" fill="#38e1ff" />

            {/* head */}
            <rect x="19" y="11" width="26" height="19" rx="8" fill="url(#hb-body)"
              stroke="#3f5e1d" strokeWidth="1" style={{ filter: "url(#hb-glow)" }} />
            <rect x="22.5" y="15.5" width="19" height="10.5" rx="5" fill="#0b1605" opacity="0.85" />
            {/* eyes */}
            <circle className="hb-eye" cx="28" cy="21" r="2.7" fill="url(#hb-eye)" />
            <circle className="hb-eye" cx="37" cy="21" r="2.7" fill="url(#hb-eye)" />
            {/* smile */}
            <path d="M28 25 q4 3 8 0" stroke="#8affd6" strokeWidth="1.2" fill="none" strokeLinecap="round" />
            {/* cheek bolts */}
            <circle cx="21" cy="20" r="1" fill="#cfe6a3" />
            <circle cx="43" cy="20" r="1" fill="#cfe6a3" />
          </svg>
        </div>
      </div>
    </div>
  );
}
