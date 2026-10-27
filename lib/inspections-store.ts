import type { Inspection } from "./api-core";

type InspectionDraft = Omit<Inspection, "id" | "created_at">;

export type InspectionPage = { items: Inspection[]; total: number };

export type InspectionStore = {
  list(cellId: string | null, limit: number, offset: number): Promise<InspectionPage>;
  create(inspection: InspectionDraft): Promise<Inspection>;
};

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export class InspectionStoreConfigurationError extends Error {}
export class InspectionStoreUnavailableError extends Error {}

function ensureInspection(value: unknown): Inspection {
  if (
    !value || typeof value !== "object" ||
    typeof (value as Inspection).id !== "string" ||
    typeof (value as Inspection).cell_id !== "string" ||
    typeof (value as Inspection).result !== "string" ||
    typeof (value as Inspection).notes !== "string" ||
    typeof (value as Inspection).created_at !== "string"
  ) {
    throw new InspectionStoreUnavailableError("The inspection store returned an invalid record.");
  }
  return value as Inspection;
}

function contentRangeTotal(value: string | null): number {
  const total = value?.match(/\/(\d+)$/)?.[1];
  return total ? Number(total) : 0;
}

export function createMemoryInspectionStore(now = () => new Date()): InspectionStore {
  const inspections: Inspection[] = [];
  return {
    async list(cellId, limit, offset) {
      const matching = inspections.filter((inspection) => cellId === null || inspection.cell_id === cellId);
      return { items: matching.slice(offset, offset + limit), total: matching.length };
    },
    async create(inspection) {
      const created = {
        id: `inspection-${String(inspections.length + 1).padStart(3, "0")}`,
        ...inspection,
        created_at: now().toISOString(),
      };
      inspections.push(created);
      return created;
    },
  };
}

export function createSupabaseInspectionStore(
  supabaseUrl: string,
  serviceRoleKey: string,
  fetchImpl: FetchLike = fetch,
): InspectionStore {
  const baseUrl = supabaseUrl.replace(/\/$/, "");
  let endpoint: URL;
  try {
    endpoint = new URL(`${baseUrl}/rest/v1/inspections`);
  } catch {
    throw new InspectionStoreConfigurationError("SUPABASE_URL must be a valid URL.");
  }
  const headers = { apikey: serviceRoleKey, Authorization: `Bearer ${serviceRoleKey}` };

  async function request(url: URL, init: RequestInit): Promise<Response> {
    let response: Response;
    try {
      response = await fetchImpl(url.toString(), init);
    } catch {
      throw new InspectionStoreUnavailableError("Could not reach the inspection store.");
    }
    if (!response.ok) throw new InspectionStoreUnavailableError("The inspection store rejected the request.");
    return response;
  }

  return {
    async list(cellId, limit, offset) {
      const url = new URL(endpoint);
      url.searchParams.set("select", "id,cell_id,result,notes,created_at");
      url.searchParams.set("order", "created_at.desc");
      url.searchParams.set("limit", String(limit));
      url.searchParams.set("offset", String(offset));
      if (cellId) url.searchParams.set("cell_id", `eq.${cellId}`);
      const response = await request(url, { headers: { ...headers, Prefer: "count=exact" } });
      const data: unknown = await response.json();
      if (!Array.isArray(data)) throw new InspectionStoreUnavailableError("The inspection store returned an invalid list.");
      return { items: data.map(ensureInspection), total: contentRangeTotal(response.headers.get("content-range")) };
    },
    async create(inspection) {
      const response = await request(endpoint, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json", Prefer: "return=representation" },
        body: JSON.stringify(inspection),
      });
      const data: unknown = await response.json();
      if (!Array.isArray(data) || data.length !== 1) {
        throw new InspectionStoreUnavailableError("The inspection store did not return the created record.");
      }
      return ensureInspection(data[0]);
    },
  };
}

const memoryStore = createMemoryInspectionStore();

function configuredStore(): InspectionStore {
  const url = process.env.SUPABASE_URL?.trim();
  // SUPABASE_SECRET_KEY is the current Supabase server key. Keep the legacy
  // name as a migration fallback for projects that have not rotated keys yet.
  const key = process.env.SUPABASE_SECRET_KEY?.trim() || process.env.SUPABASE_SERVICE_ROLE_KEY?.trim();
  if (url || key) {
    if (!url || !key) throw new InspectionStoreConfigurationError("Set both SUPABASE_URL and SUPABASE_SECRET_KEY.");
    return createSupabaseInspectionStore(url, key);
  }
  if (process.env.NODE_ENV === "production") {
    throw new InspectionStoreConfigurationError("Persistent inspection storage is not configured.");
  }
  return memoryStore;
}

export async function listInspections(cellId: string | null, limit: number, offset: number): Promise<InspectionPage> {
  return configuredStore().list(cellId, limit, offset);
}

export async function createInspection(inspection: InspectionDraft): Promise<Inspection> {
  return configuredStore().create(inspection);
}
