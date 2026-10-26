"use client";

import { useEffect, useRef } from "react";
import { createScene, STILL_TIME, type SceneKind } from "@/lib/landing/scenes";

/**
 * Full-bleed animated background. Animates only while on screen and the tab is
 * visible; with prefers-reduced-motion it draws a single still frame instead.
 */
export function Backdrop({ scene, seed = 1 }: { scene: SceneKind; seed?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    const draw = createScene(scene, seed);
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    const start = performance.now();
    let width = 0;
    let height = 0;
    let frame = 0;
    let onScreen = false;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      const rect = canvas.getBoundingClientRect();
      width = rect.width;
      height = rect.height;
      canvas.width = Math.max(1, Math.round(width * dpr));
      canvas.height = Math.max(1, Math.round(height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    const paint = (now: number) => {
      draw(ctx, width, height, reduced.matches ? STILL_TIME[scene] : (now - start) / 1000);
    };
    const loop = (now: number) => {
      paint(now);
      frame = requestAnimationFrame(loop);
    };
    const update = () => {
      cancelAnimationFrame(frame);
      if (!onScreen) return;
      if (reduced.matches || document.hidden) paint(performance.now());
      else frame = requestAnimationFrame(loop);
    };

    const resizeObserver = new ResizeObserver(() => {
      resize();
      paint(performance.now());
    });
    const visibility = new IntersectionObserver(([entry]) => {
      onScreen = entry.isIntersecting;
      update();
    });
    resize();
    paint(performance.now());
    resizeObserver.observe(canvas);
    visibility.observe(canvas);
    document.addEventListener("visibilitychange", update);
    reduced.addEventListener("change", update);

    return () => {
      cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      visibility.disconnect();
      document.removeEventListener("visibilitychange", update);
      reduced.removeEventListener("change", update);
    };
  }, [scene, seed]);

  return <canvas ref={ref} className="lp-canvas" aria-hidden />;
}
