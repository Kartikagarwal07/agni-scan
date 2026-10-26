import { useEffect, useState } from "react";
import { ApiError, fetchJson } from "@/lib/dashboard/api";

export type ApiState<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; error: ApiError }
  | { status: "success"; data: T };

type Settled<T> = { key: string; data?: T; error?: ApiError };

/**
 * Fetches `url` (or nothing when it is null) and re-fetches when it changes.
 * Loading is derived from whether the last settled request matches the current
 * one, so state is only set from async callbacks, and stale responses are ignored.
 */
export function useApi<T>(url: string | null, parse: (body: unknown) => T) {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const key = url === null ? null : `${attempt}:${url}`;

  useEffect(() => {
    if (url === null || key === null) return;
    const controller = new AbortController();
    fetchJson(url, parse, controller.signal).then(
      (data) => setSettled({ key, data }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        const apiError =
          error instanceof ApiError ? error : new ApiError(0, "CLIENT_ERROR", "Unexpected error while loading data.");
        setSettled({ key, error: apiError });
      },
    );
    return () => controller.abort();
  }, [url, key, parse]);

  let state: ApiState<T>;
  if (key === null) state = { status: "idle" };
  else if (settled?.key !== key) state = { status: "loading" };
  else if (settled.error) state = { status: "error", error: settled.error };
  else state = { status: "success", data: settled.data as T };

  return { state, retry: () => setAttempt((n) => n + 1) };
}
