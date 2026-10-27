import assert from "node:assert/strict";
import test from "node:test";
import {
  createMemoryInspectionStore,
  createSupabaseInspectionStore,
  InspectionStoreUnavailableError,
} from "../lib/inspections-store.ts";

const draft = { cell_id: "PB-5000M-N00679-E00085", result: "inconclusive" as const, notes: "No clear residue evidence." };

test("memory inspection store persists records for its server lifetime and paginates", async () => {
  const store = createMemoryInspectionStore(() => new Date("2026-10-28T09:00:00Z"));
  const first = await store.create(draft);
  const second = await store.create({ ...draft, result: "fire_evidence_found" });
  assert.equal(first.id, "inspection-001");
  assert.equal(second.id, "inspection-002");
  assert.deepEqual(await store.list(draft.cell_id, 1, 1), { items: [second], total: 2 });
});

test("Supabase inspection store sends server credentials only to the Supabase REST endpoint", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const store = createSupabaseInspectionStore("https://example.supabase.co/", "server-secret", async (url, init) => {
    calls.push({ url, init });
    return new Response(JSON.stringify([{ id: "db-id", ...draft, created_at: "2026-10-28T09:00:00Z" }]), { status: 201 });
  });
  const created = await store.create(draft);
  assert.equal(created.id, "db-id");
  assert.equal(calls[0].url, "https://example.supabase.co/rest/v1/inspections");
  assert.equal(new Headers(calls[0].init?.headers).get("apikey"), "server-secret");
  assert.equal(new Headers(calls[0].init?.headers).get("prefer"), "return=representation");
});

test("Supabase inspection store uses database pagination and reports unavailable storage", async () => {
  const requests: string[] = [];
  const store = createSupabaseInspectionStore("https://example.supabase.co", "server-secret", async (url) => {
    requests.push(url);
    return new Response(JSON.stringify([{ id: "db-id", ...draft, created_at: "2026-10-28T09:00:00Z" }]), {
      status: 200,
      headers: { "content-range": "0-0/7" },
    });
  });
  assert.deepEqual(await store.list(draft.cell_id, 10, 20), {
    items: [{ id: "db-id", ...draft, created_at: "2026-10-28T09:00:00Z" }], total: 7,
  });
  assert.match(requests[0], /cell_id=eq.PB-5000M-N00679-E00085/);
  assert.match(requests[0], /limit=10/);
  assert.match(requests[0], /offset=20/);

  const unavailable = createSupabaseInspectionStore("https://example.supabase.co", "server-secret", async () => {
    throw new Error("offline");
  });
  await assert.rejects(() => unavailable.list(null, 10, 0), InspectionStoreUnavailableError);
});
