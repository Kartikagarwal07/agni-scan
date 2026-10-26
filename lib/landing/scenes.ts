// Animated canvas backdrops for the landing page. They are illustrations drawn
// in code, not imagery or data: nothing here depicts a real place or real fires.
// Each frame is a pure function of (width, height, time), so scenes can be paused,
// resized or drawn once for reduced motion without drifting.
import { hash2, mulberry32 } from "./random.ts";

export type SceneKind = "orbit" | "embers" | "grid" | "contours";
export type Scene = (ctx: CanvasRenderingContext2D, w: number, h: number, t: number) => void;

/** Time used for the single still frame shown when motion is reduced. */
export const STILL_TIME: Record<SceneKind, number> = { orbit: 9, embers: 14, grid: 6, contours: 11 };

const TAU = Math.PI * 2;
const RISK = { high: "226,85,74", medium: "240,160,32", low: "95,158,138" } as const;

type Rand = () => number;
const range = (rand: Rand, min: number, max: number) => min + rand() * (max - min);
const frac = (x: number) => x - Math.floor(x);

export function createScene(kind: SceneKind, seed = 1): Scene {
  const rand = mulberry32(seed);
  switch (kind) {
    case "orbit":
      return orbitScene(rand);
    case "embers":
      return embersScene(rand);
    case "grid":
      return gridScene(seed);
    case "contours":
      return contoursScene(rand);
  }
}

/** A satellite crosses above a night-side planet; hotspots flare as its scan swath passes. */
function orbitScene(rand: Rand): Scene {
  const stars = Array.from({ length: 160 }, () => ({
    x: rand(), y: rand(), r: range(rand, 0.3, 1.3), phase: range(rand, 0, TAU), speed: range(rand, 0.4, 1.4),
  }));
  // Hotspots in normalised (x across, depth below the limb) coordinates.
  const spots = Array.from({ length: 34 }, () => ({ x: range(rand, 0.06, 0.94), depth: range(rand, 0.04, 0.55), size: range(rand, 0.6, 1.4) }));

  return (ctx, w, h, t) => {
    ctx.globalCompositeOperation = "source-over";
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, w, h);

    for (const s of stars) {
      const a = 0.25 + 0.55 * (0.5 + 0.5 * Math.sin(t * s.speed + s.phase));
      ctx.fillStyle = `rgba(255,255,255,${a.toFixed(3)})`;
      ctx.beginPath();
      ctx.arc(s.x * w, s.y * h * 0.75, s.r, 0, TAU);
      ctx.fill();
    }

    const R = Math.max(w, h) * 1.25;
    const cx = w * 0.5;
    const cy = h * 0.62 + R;
    const top = (x: number) => cy - Math.sqrt(Math.max(R * R - (x - cx) ** 2, 0));

    // Atmosphere glow, then the planet body.
    const glow = ctx.createRadialGradient(cx, cy, R * 0.985, cx, cy, R * 1.06);
    glow.addColorStop(0, "rgba(70,130,255,0.0)");
    glow.addColorStop(0.22, "rgba(110,170,255,0.55)");
    glow.addColorStop(1, "rgba(40,80,200,0)");
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(cx, cy, R * 1.06, 0, TAU);
    ctx.fill();

    const body = ctx.createRadialGradient(cx, cy - R, 0, cx, cy - R * 0.6, R * 0.9);
    body.addColorStop(0, "#16233d");
    body.addColorStop(1, "#02050b");
    ctx.fillStyle = body;
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, TAU);
    ctx.fill();

    // Slowly turning meridians give a sense of rotation.
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, TAU);
    ctx.clip();
    ctx.strokeStyle = "rgba(130,170,255,0.11)";
    ctx.lineWidth = 1;
    for (let k = 0; k < 14; k++) {
      const a = (k / 14) * Math.PI + t * 0.015;
      ctx.beginPath();
      ctx.ellipse(cx, cy, Math.abs(Math.cos(a)) * R, R, 0, 0, TAU);
      ctx.stroke();
    }
    ctx.restore();

    // Satellite position and its scan swath.
    const sweep = frac(t * 0.045) * 1.5 - 0.25;
    const sx = sweep * w;
    const limb = top(sx);
    const sy = limb - h * 0.2;
    const swath = w * 0.07;

    ctx.globalCompositeOperation = "lighter";
    const cone = ctx.createLinearGradient(0, sy, 0, limb + h * 0.1);
    cone.addColorStop(0, "rgba(255,150,60,0.18)");
    cone.addColorStop(1, "rgba(255,120,40,0)");
    ctx.fillStyle = cone;
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(sx + swath, top(sx + swath) + h * 0.1);
    ctx.lineTo(sx - swath, top(sx - swath) + h * 0.1);
    ctx.closePath();
    ctx.fill();

    for (const p of spots) {
      const px = p.x * w;
      const py = top(px) + p.depth * h * 0.45;
      if (py > h) continue;
      const lit = Math.exp(-(((px - sx) / (swath * 1.4)) ** 2));
      const r = (3 + lit * 22) * p.size;
      const g = ctx.createRadialGradient(px, py, 0, px, py, r);
      g.addColorStop(0, `rgba(255,170,80,${(0.5 + lit * 0.5).toFixed(3)})`);
      g.addColorStop(1, "rgba(255,90,20,0)");
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(px, py, r, 0, TAU);
      ctx.fill();
    }

    // Trail and satellite.
    ctx.strokeStyle = "rgba(255,255,255,0.25)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i <= 40; i++) {
      const x = sx - (i / 40) * w * 0.35;
      const y = top(x) - h * 0.2;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.fillStyle = "rgba(255,255,255,0.95)";
    ctx.beginPath();
    ctx.arc(sx, sy, 2.4, 0, TAU);
    ctx.fill();
    ctx.globalCompositeOperation = "source-over";
  };
}

/** Dusk over a stubble field: smoke drifts up and embers rise from a burning horizon. */
function embersScene(rand: Rand): Scene {
  const fires = Array.from({ length: 9 }, () => ({ x: range(rand, 0.02, 0.98), phase: range(rand, 0, TAU), size: range(rand, 0.6, 1.3) }));
  const smoke = Array.from({ length: 16 }, () => ({ x: range(rand, 0, 1), speed: range(rand, 0.025, 0.05), phase: rand() }));
  const embers = Array.from({ length: 170 }, () => ({
    x: range(rand, 0, 1), speed: range(rand, 0.05, 0.16), phase: rand(), size: range(rand, 0.6, 2.2), hue: range(rand, 18, 42),
  }));

  return (ctx, w, h, t) => {
    const horizon = h * 0.7;
    ctx.globalCompositeOperation = "source-over";
    const sky = ctx.createLinearGradient(0, 0, 0, horizon);
    sky.addColorStop(0, "#030202");
    sky.addColorStop(0.6, "#160804");
    sky.addColorStop(1, "#4a1806");
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, w, horizon);
    const ground = ctx.createLinearGradient(0, horizon, 0, h);
    ground.addColorStop(0, "#1a0904");
    ground.addColorStop(1, "#030101");
    ctx.fillStyle = ground;
    ctx.fillRect(0, horizon, w, h - horizon);

    // Stubble rows in perspective.
    ctx.strokeStyle = "rgba(255,130,50,0.07)";
    ctx.lineWidth = 1;
    for (let i = -24; i <= 24; i++) {
      ctx.beginPath();
      ctx.moveTo(w * 0.5 + i * w * 0.012, horizon);
      ctx.lineTo(w * 0.5 + i * w * 0.12, h);
      ctx.stroke();
    }

    ctx.globalCompositeOperation = "lighter";
    for (const f of fires) {
      const flicker = 0.55 + 0.25 * Math.sin(t * 2.3 + f.phase) + 0.2 * Math.sin(t * 5.1 + f.phase * 3);
      const r = h * 0.22 * f.size;
      const g = ctx.createRadialGradient(f.x * w, horizon, 0, f.x * w, horizon, r);
      g.addColorStop(0, `rgba(255,120,30,${(0.32 * flicker).toFixed(3)})`);
      g.addColorStop(1, "rgba(255,60,0,0)");
      ctx.fillStyle = g;
      ctx.fillRect(f.x * w - r, horizon - r, r * 2, r * 2);
    }

    ctx.globalCompositeOperation = "source-over";
    for (const s of smoke) {
      const p = frac(t * s.speed + s.phase);
      const x = s.x * w + Math.sin(t * 0.2 + s.phase * TAU) * 40 + p * w * 0.12;
      const y = horizon - p * h * 0.85;
      const r = 70 + p * 300;
      const a = 0.14 * (1 - p) * Math.min(1, p * 6);
      const g = ctx.createRadialGradient(x, y, 0, x, y, r);
      g.addColorStop(0, `rgba(110,95,88,${a.toFixed(3)})`);
      g.addColorStop(1, "rgba(60,50,45,0)");
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(x, y, r, 0, TAU);
      ctx.fill();
    }

    ctx.globalCompositeOperation = "lighter";
    for (const e of embers) {
      const p = frac(t * e.speed + e.phase);
      const x = e.x * w + Math.sin(t * 1.4 + e.phase * 20) * 14 + p * 70;
      const y = horizon + 10 - p * h * 0.8;
      const a = (1 - p) * (0.55 + 0.45 * Math.sin(t * 11 + e.phase * 40));
      if (a <= 0.02) continue;
      ctx.fillStyle = `hsla(${e.hue.toFixed(0)},100%,62%,${a.toFixed(3)})`;
      ctx.beginPath();
      ctx.arc(x, y, e.size, 0, TAU);
      ctx.fill();
    }
    ctx.globalCompositeOperation = "source-over";
  };
}

/** A grid of cells; a scan line sweeps across and briefly reveals each cell's priority colour. */
function gridScene(seed: number): Scene {
  return (ctx, w, h, t) => {
    ctx.globalCompositeOperation = "source-over";
    ctx.fillStyle = "#040404";
    ctx.fillRect(0, 0, w, h);

    const size = Math.max(34, Math.min(w, h) / 14);
    const ox = t * 7;
    const oy = t * 3;
    const scan = (frac(t * 0.07) * 1.3 - 0.15) * w;
    const i0 = Math.floor(ox / size) - 1;
    const j0 = Math.floor(oy / size) - 1;
    const cols = Math.ceil(w / size) + 2;
    const rows = Math.ceil(h / size) + 2;

    for (let i = i0; i < i0 + cols; i++) {
      for (let j = j0; j < j0 + rows; j++) {
        const x = i * size - ox;
        const y = j * size - oy;
        const v = hash2(i, j, seed);
        const behind = scan - (x + size / 2);
        // Bright just after the scan line passes, fading to a faint tint.
        const reveal = behind >= 0 ? Math.exp(-behind / (w * 0.22)) : 0;
        const pad = 2;
        if (v > 0.84) {
          ctx.strokeStyle = `rgba(160,160,155,${(0.12 + 0.4 * reveal).toFixed(3)})`;
          ctx.lineWidth = 1;
          ctx.save();
          ctx.beginPath();
          ctx.rect(x + pad, y + pad, size - pad * 2, size - pad * 2);
          ctx.clip();
          for (let k = -size; k < size; k += 6) {
            ctx.beginPath();
            ctx.moveTo(x + k, y + size);
            ctx.lineTo(x + k + size, y);
            ctx.stroke();
          }
          ctx.restore();
          continue;
        }
        const rgb = v < 0.05 ? RISK.high : v < 0.13 ? RISK.medium : RISK.low;
        const base = rgb === RISK.low ? 0.05 : 0.12;
        ctx.fillStyle = `rgba(${rgb},${(base + reveal * (rgb === RISK.low ? 0.45 : 0.85)).toFixed(3)})`;
        ctx.fillRect(x + pad, y + pad, size - pad * 2, size - pad * 2);
      }
    }

    const line = ctx.createLinearGradient(scan - 80, 0, scan + 4, 0);
    line.addColorStop(0, "rgba(255,255,255,0)");
    line.addColorStop(1, "rgba(255,255,255,0.22)");
    ctx.fillStyle = line;
    ctx.fillRect(scan - 80, 0, 84, h);
    ctx.fillStyle = "rgba(255,255,255,0.7)";
    ctx.fillRect(scan, 0, 1.5, h);

    const vignette = ctx.createRadialGradient(w / 2, h / 2, Math.min(w, h) * 0.2, w / 2, h / 2, Math.max(w, h) * 0.75);
    vignette.addColorStop(0, "rgba(0,0,0,0)");
    vignette.addColorStop(1, "rgba(0,0,0,0.85)");
    ctx.fillStyle = vignette;
    ctx.fillRect(0, 0, w, h);
  };
}

/** Terrain contours with a field team's route to an inspection point. */
function contoursScene(rand: Rand): Scene {
  const centres = Array.from({ length: 4 }, () => ({ x: range(rand, 0.1, 0.9), y: range(rand, 0.1, 0.9), p1: range(rand, 0, TAU), p2: range(rand, 0, TAU) }));
  const waypoints = [
    { x: 0.08, y: 0.86 },
    { x: 0.3, y: range(rand, 0.55, 0.75) },
    { x: 0.5, y: range(rand, 0.6, 0.8) },
    { x: 0.68, y: range(rand, 0.35, 0.5) },
    { x: 0.82, y: range(rand, 0.25, 0.4) },
  ];

  return (ctx, w, h, t) => {
    ctx.globalCompositeOperation = "source-over";
    ctx.fillStyle = "#020403";
    ctx.fillRect(0, 0, w, h);

    const spacing = Math.max(w, h) / 22;
    ctx.lineWidth = 1;
    for (const c of centres) {
      const drift = frac(t * 0.04) * spacing;
      for (let k = 0; k < 16; k++) {
        const r0 = k * spacing + drift;
        const fade = 1 - k / 16;
        ctx.strokeStyle = `rgba(140,205,165,${(0.13 * fade).toFixed(3)})`;
        ctx.beginPath();
        for (let s = 0; s <= 72; s++) {
          const a = (s / 72) * TAU;
          const rr = r0 * (1 + 0.14 * Math.sin(3 * a + c.p1) + 0.07 * Math.sin(5 * a - t * 0.08 + c.p2));
          const x = c.x * w + Math.cos(a) * rr;
          const y = c.y * h + Math.sin(a) * rr * 0.8;
          if (s === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }
    }

    // Route, sampled as a polyline so a marker can travel along it.
    const pts: [number, number][] = [];
    for (let i = 0; i < waypoints.length - 1; i++) {
      const a = waypoints[i];
      const b = waypoints[i + 1];
      for (let s = 0; s < 20; s++) {
        const u = s / 20;
        const e = u * u * (3 - 2 * u);
        pts.push([(a.x + (b.x - a.x) * u) * w, (a.y + (b.y - a.y) * e) * h]);
      }
    }
    const end = waypoints[waypoints.length - 1];
    pts.push([end.x * w, end.y * h]);

    ctx.strokeStyle = "rgba(255,255,255,0.45)";
    ctx.lineWidth = 1.5;
    ctx.setLineDash([6, 8]);
    ctx.lineDashOffset = -t * 12;
    ctx.beginPath();
    pts.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
    ctx.stroke();
    ctx.setLineDash([]);

    const progress = frac(t * 0.05);
    const [mx, my] = pts[Math.min(pts.length - 1, Math.floor(progress * (pts.length - 1)))];
    ctx.fillStyle = "#fff";
    ctx.beginPath();
    ctx.arc(mx, my, 3.5, 0, TAU);
    ctx.fill();

    // Inspection point: pulsing rings.
    ctx.globalCompositeOperation = "lighter";
    const ex = end.x * w;
    const ey = end.y * h;
    for (let k = 0; k < 3; k++) {
      const p = frac(t * 0.35 + k / 3);
      ctx.strokeStyle = `rgba(255,150,60,${(0.6 * (1 - p)).toFixed(3)})`;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(ex, ey, 6 + p * 46, 0, TAU);
      ctx.stroke();
    }
    ctx.fillStyle = "rgba(255,160,70,0.95)";
    ctx.beginPath();
    ctx.arc(ex, ey, 5, 0, TAU);
    ctx.fill();
    ctx.globalCompositeOperation = "source-over";
  };
}
