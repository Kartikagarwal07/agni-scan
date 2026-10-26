import assert from "node:assert/strict";
import test from "node:test";
import { DEMO_GRID, gridFor, parseInspection, parsePagination, RequestValidationError } from "../lib/api-core.ts";

test("demo grid conforms to the shared feature invariants", () => {
  assert.ok(DEMO_GRID.length > 0);
  for (const feature of DEMO_GRID) {
    assert.equal(feature.id, feature.properties.cell_id);
    assert.equal(feature.geometry.type, "Polygon");
    const ring = feature.geometry.coordinates[0];
    assert.deepEqual(ring[0], ring[ring.length - 1]);
  }
});

test("grid filters and priority pagination use contract query parameters", () => {
  assert.deepEqual(gridFor(new URLSearchParams("district=Ludhiana")).map((cell) => cell.id), ["PB-001", "PB-002"]);
  assert.deepEqual(parsePagination(new URLSearchParams("limit=1&offset=2")), { limit: 1, offset: 2 });
  assert.throws(() => parsePagination(new URLSearchParams("limit=101")), RequestValidationError);
});

test("inspection validation accepts only a real cell and allowed result", () => {
  assert.deepEqual(parseInspection({ cell_id: "PB-001", result: "inconclusive", notes: "  Demo field check  " }), {
    cell_id: "PB-001", result: "inconclusive", notes: "Demo field check",
  });
  assert.throws(() => parseInspection({ cell_id: "PB-999", result: "inconclusive", notes: "No cell" }), RequestValidationError);
  assert.throws(() => parseInspection({ cell_id: "PB-001", result: "other", notes: "No" }), RequestValidationError);
});
