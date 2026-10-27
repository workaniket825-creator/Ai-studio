import { useEffect, useRef } from "react";
import { Button } from "@blueprintjs/core";

export function Landing({ onEnter }: { onEnter: () => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current!;
    const ctx = canvas.getContext("2d")!;
    let raf = 0, t = 0;
    const DPR = Math.min(2, window.devicePixelRatio || 1);

    const resize = () => {
      canvas.width = canvas.offsetWidth * DPR;
      canvas.height = canvas.offsetHeight * DPR;
    };
    resize();
    window.addEventListener("resize", resize);

    // starfield
    const stars = Array.from({ length: 220 }, () => ({
      x: Math.random(), y: Math.random(), z: Math.random() * 0.8 + 0.2,
      tw: Math.random() * Math.PI * 2,
    }));

    // globe points (lat/long grid → sphere)
    const pts: { lat: number; lon: number }[] = [];
    for (let lat = -80; lat <= 80; lat += 10)
      for (let lon = -180; lon < 180; lon += 10)
        if (Math.random() > 0.35) pts.push({ lat: (lat * Math.PI) / 180, lon: (lon * Math.PI) / 180 });

    // arcs between random points
    const arcs = Array.from({ length: 14 }, () => ({
      a: pts[(Math.random() * pts.length) | 0], b: pts[(Math.random() * pts.length) | 0],
      p: Math.random(), speed: 0.002 + Math.random() * 0.004,
    }));

    const draw = () => {
      const W = canvas.width, H = canvas.height;
      const cx = W / 2, cy = H * 0.46, R = Math.min(W, H) * 0.28;
      ctx.clearRect(0, 0, W, H);

      // background radial glow
      const g = ctx.createRadialGradient(cx, cy, R * 0.2, cx, cy, R * 3);
      g.addColorStop(0, "rgba(118,185,0,0.10)");
      g.addColorStop(1, "rgba(6,10,7,0)");
      ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);

      // stars
      stars.forEach((s) => {
        const a = 0.4 + 0.6 * Math.abs(Math.sin(t * 0.03 + s.tw));
        ctx.fillStyle = `rgba(200,230,190,${a * s.z})`;
        ctx.fillRect(s.x * W, s.y * H, DPR * s.z, DPR * s.z);
      });

      const rot = t * 0.006;
      const project = (lat: number, lon: number) => {
        const x = Math.cos(lat) * Math.sin(lon + rot);
        const y = Math.sin(lat);
        const z = Math.cos(lat) * Math.cos(lon + rot);
        return { sx: cx + x * R, sy: cy - y * R, z };
      };

      // globe glow ring
      ctx.beginPath(); ctx.arc(cx, cy, R * 1.04, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(118,185,0,0.35)"; ctx.lineWidth = DPR * 1.5; ctx.stroke();

      // points
      pts.forEach((p) => {
        const { sx, sy, z } = project(p.lat, p.lon);
        if (z < -0.1) return;
        const a = 0.25 + 0.75 * z;
        ctx.fillStyle = `rgba(140,220,40,${a})`;
        const r = DPR * (0.7 + z * 1.4);
        ctx.beginPath(); ctx.arc(sx, sy, r, 0, Math.PI * 2); ctx.fill();
      });

      // arcs
      arcs.forEach((arc) => {
        arc.p += arc.speed; if (arc.p > 1) arc.p = 0;
        const A = project(arc.a.lat, arc.a.lon), B = project(arc.b.lat, arc.b.lon);
        if (A.z < -0.2 && B.z < -0.2) return;
        const mx = (A.sx + B.sx) / 2, my = (A.sy + B.sy) / 2 - R * 0.5;
        ctx.beginPath(); ctx.moveTo(A.sx, A.sy); ctx.quadraticCurveTo(mx, my, B.sx, B.sy);
        ctx.strokeStyle = "rgba(118,185,0,0.18)"; ctx.lineWidth = DPR; ctx.stroke();
        // travelling pulse
        const tt = arc.p, ix = (1 - tt) * (1 - tt) * A.sx + 2 * (1 - tt) * tt * mx + tt * tt * B.sx;
        const iy = (1 - tt) * (1 - tt) * A.sy + 2 * (1 - tt) * tt * my + tt * tt * B.sy;
        ctx.fillStyle = "rgba(180,240,60,0.95)";
        ctx.beginPath(); ctx.arc(ix, iy, DPR * 2, 0, Math.PI * 2); ctx.fill();
      });

      // reflection under the globe
      const rg = ctx.createLinearGradient(0, cy + R, 0, cy + R * 2.2);
      rg.addColorStop(0, "rgba(118,185,0,0.10)"); rg.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = rg; ctx.fillRect(cx - R, cy + R, R * 2, R * 1.2);

      t += 1; raf = requestAnimationFrame(draw);
    };
    draw();
    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", resize); };
  }, []);

  return (
    <div className="landing">
      <canvas ref={canvasRef} className="landing-canvas" />
      <div className="landing-overlay">
        <div className="landing-badge">ENTERPRISE · AGENTIC · OBSERVABLE</div>
        <h1 className="landing-title">TCS <span>AI Studio</span></h1>
        <div className="landing-ver">v1.0</div>
        <p className="landing-sub">
          Build, run and observe enterprise agentic workflows on a single operational canvas —
          agents, tools, connectors, and full-trace observability.
        </p>
        <Button large intent="primary" rightIcon="arrow-right" className="landing-cta"
          text="Enter platform" onClick={onEnter} />
        <div className="landing-foot">© 2026 Tata Consultancy Services. All rights reserved.</div>
      </div>
    </div>
  );
}
