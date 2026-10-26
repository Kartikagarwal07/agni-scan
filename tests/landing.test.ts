import assert from "node:assert/strict";
import test from "node:test";
import { hash2, mulberry32 } from "../lib/landing/random.ts";
import { createScene, STILL_TIME, type SceneKind } from "../lib/landing/scenes.ts";

const SCENES: SceneKind[] = ["orbit", "embers", "grid", "contours"];

/** Canvas 2D stand-in that records every call, so scenes can run without a browser. */
function recordingContext() {
  const calls: { name: string; args: unknown[] }[] = [];
  let gradients = 0;
  // Gradients are recorded by creation order so two runs compare structurally.
  const gradient = () => {
    const label = `gradient#${gradients++}`;
    return { label, addColorStop: (...args: unknown[]) => calls.push({ name: `${label}.addColorStop`, args }) };
  };
  const ctx = new Proxy({} as Record<string, unknown>, {
    get(target, prop: string) {
      if (prop in target) return target[prop];
      return (...args: unknown[]) => {
        calls.push({ name: prop, args });
        return prop.startsWith("create") ? gradient() : undefined;
      };
    },
    set(target, prop: string, value) {
      target[prop] = value;
      const recorded = typeof value === "object" && value !== null && "label" in value ? value.label : value;
      calls.push({ name: `set:${prop}`, args: [recorded] });
      return true;
    },
  });
  return { ctx: ctx as unknown as CanvasRenderingContext2D, calls };
}

test("seeded random is deterministic and in [0, 1)", () => {
  const a = mulberry32(42);
  const b = mulberry32(42);
  const seqA = Array.from({ length: 100 }, a);
  assert.deepEqual(seqA, Array.from({ length: 100 }, b));
  assert.notDeepEqual(seqA, Array.from({ length: 100 }, mulberry32(43)));
  for (const v of seqA) assert.ok(v >= 0 && v < 1);
  for (let i = -50; i < 50; i++) {
    const v = hash2(i, i * 3 - 7, 5);
    assert.ok(v >= 0 && v < 1);
    assert.equal(v, hash2(i, i * 3 - 7, 5));
  }
});

for (const kind of SCENES) {
  test(`${kind} scene draws finite geometry and is a pure function of time`, () => {
    for (const [w, h] of [[1400, 900], [390, 844], [1, 1]]) {
      for (const t of [0, 0.5, STILL_TIME[kind], 123.4]) {
        const first = recordingContext();
        createScene(kind, 3)(first.ctx, w, h, t);
        assert.ok(first.calls.length > 10, "scene should draw something");
        for (const call of first.calls) {
          for (const arg of call.args) {
            if (typeof arg === "number") assert.ok(Number.isFinite(arg), `${kind}: ${call.name} got ${arg} at ${w}x${h}, t=${t}`);
            if (typeof arg === "string") assert.ok(!/NaN|Infinity/.test(arg), `${kind}: ${call.name} got "${arg}"`);
          }
        }
        const second = recordingContext();
        createScene(kind, 3)(second.ctx, w, h, t);
        assert.deepEqual(second.calls, first.calls, "same seed and time must draw the same frame");
      }
    }
  });
}

test("scenes move over time", () => {
  for (const kind of SCENES) {
    const a = recordingContext();
    const b = recordingContext();
    const scene = createScene(kind, 3);
    scene(a.ctx, 800, 600, 1);
    scene(b.ctx, 800, 600, 2);
    assert.notDeepEqual(a.calls, b.calls, `${kind} should change between frames`);
  }
});
