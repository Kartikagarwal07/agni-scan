import type { ReactNode } from "react";
import type { ApiError } from "@/lib/dashboard/api";

export function Loading({ label }: { label: string }) {
  return (
    <div role="status" aria-live="polite" className="ag-loading">
      <span className="ag-dot ag-pulse" aria-hidden />
      {label}
    </div>
  );
}

export function ErrorState({ title, error, onRetry }: { title: string; error: ApiError; onRetry?: () => void }) {
  return (
    <div role="alert" className="ag-error">
      <p className="ag-errorTitle">{title}</p>
      <p>{error.message}</p>
      <p className="ag-mono ag-small ag-muted">
        {error.code}
        {error.status ? ` · HTTP ${error.status}` : ""}
      </p>
      {onRetry && (
        <p>
          <button type="button" onClick={onRetry} className="ag-button ag-buttonSmall">
            Try again
          </button>
        </p>
      )}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="ag-empty">
      <p className="ag-emptyTitle">{title}</p>
      {children && <p className="ag-muted">{children}</p>}
    </div>
  );
}
