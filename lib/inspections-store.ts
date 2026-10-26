import type { Inspection } from "./api-core";

// Deliberately in-memory demo storage. It resets on server restart and must be
// replaced by an authenticated persistent store before a public deployment.
const inspections: Inspection[] = [];

export function listInspections(cellId: string | null) {
  return inspections.filter((inspection) => cellId === null || inspection.cell_id === cellId);
}

export function createInspection(inspection: Omit<Inspection, "id" | "created_at">): Inspection {
  const id = `inspection-${String(inspections.length + 1).padStart(3, "0")}`;
  const created = { id, ...inspection, created_at: new Date().toISOString() };
  inspections.push(created);
  return created;
}
