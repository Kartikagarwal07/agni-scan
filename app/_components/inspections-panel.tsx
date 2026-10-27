import { useState, type FormEvent } from "react";
import type { Inspection, InspectionResult } from "@/lib/api-core";
import {
  ApiError,
  createInspection,
  INSPECTION_RESULTS,
  inspectionDraftError,
  NOTES_MAX_LENGTH,
  type InspectionPage,
} from "@/lib/dashboard/api";
import { formatTimestamp, INSPECTION_RESULT_LABEL } from "@/lib/dashboard/format";
import { Pager } from "./pager";
import { EmptyState, ErrorState, Loading } from "./status";
import type { ApiState } from "./use-api";

type ListProps = {
  cellId: string | null;
  state: ApiState<InspectionPage>;
  onPage: (offset: number) => void;
  onLimit: (limit: number) => void;
  onRetry: () => void;
};

/** GET /api/inspections, for the selected cell (cell_id) or for all cells. */
export function InspectionList({ cellId, state, onPage, onLimit, onRetry }: ListProps) {
  if (state.status === "idle" || state.status === "loading") return <Loading label="Loading inspections…" />;
  if (state.status === "error") return <ErrorState title="Could not load inspections" error={state.error} onRetry={onRetry} />;

  const { items, total, limit, offset } = state.data;
  return (
    <div>
      {items.length === 0 ? (
        <EmptyState title="No inspections recorded">
          {total > 0 ? "This page is past the end of the list." : cellId ? "Nothing has been recorded for this cell yet." : "Nothing has been recorded yet."}
        </EmptyState>
      ) : (
        <ul className="ag-inspections">
          {items.map((inspection) => (
            <InspectionItem key={inspection.id} inspection={inspection} showCell={!cellId} />
          ))}
        </ul>
      )}
      <Pager total={total} offset={offset} limit={limit} shown={items.length} onPage={onPage} onLimit={onLimit} />
    </div>
  );
}

function InspectionItem({ inspection, showCell }: { inspection: Inspection; showCell: boolean }) {
  return (
    <li>
      <p className="ag-inspectionHead">
        <span className={`ag-result ag-result_${inspection.result}`}>{INSPECTION_RESULT_LABEL[inspection.result]}</span>
        <span className="ag-muted ag-small">{formatTimestamp(inspection.created_at)}</span>
      </p>
      {showCell && <p className="ag-mono ag-small">{inspection.cell_id}</p>}
      <p className="ag-inspectionNotes">{inspection.notes}</p>
      <p className="ag-muted ag-small ag-mono">{inspection.id}</p>
    </li>
  );
}

type FormProps = { cellId: string; onCreated: (inspection: Inspection) => void };

type Feedback = { kind: "success" | "error"; text: string; code?: string };

/**
 * POST /api/inspections. Mount with key={cellId} so the form resets per cell.
 * Recording an inspection does not change the cell's verification_status; the
 * backend does not link the two.
 */
export function InspectionForm({ cellId, onCreated }: FormProps) {
  const [result, setResult] = useState<InspectionResult | "">("");
  const [notes, setNotes] = useState("");
  const [writeToken, setWriteToken] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const draft = { cell_id: cellId, result, notes };
    const problem = inspectionDraftError(draft);
    if (problem) {
      setFeedback({ kind: "error", text: problem });
      return;
    }
    setSubmitting(true);
    setFeedback(null);
    try {
      const created = await createInspection(draft, writeToken);
      setResult("");
      setNotes("");
      setFeedback({ kind: "success", text: `Saved as ${created.id} at ${formatTimestamp(created.created_at)}.` });
      onCreated(created);
    } catch (error) {
      const apiError = error instanceof ApiError ? error : new ApiError(0, "CLIENT_ERROR", "Unexpected error while saving.");
      const text =
        apiError.code === "WRITE_NOT_AUTHORIZED"
          ? "The server requires a valid write token for inspections. Enter it below and try again."
          : apiError.message;
      setFeedback({ kind: "error", text, code: `${apiError.code}${apiError.status ? ` · HTTP ${apiError.status}` : ""}` });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="ag-form" onSubmit={onSubmit} noValidate>
      <fieldset className="ag-fieldset" disabled={submitting}>
        <legend className="ag-legendTitle">Result</legend>
        {INSPECTION_RESULTS.map((value) => (
          <label key={value} className="ag-radio">
            <input
              type="radio"
              name="inspection-result"
              value={value}
              checked={result === value}
              onChange={() => setResult(value)}
            />
            {INSPECTION_RESULT_LABEL[value]}
          </label>
        ))}
      </fieldset>

      <label className="ag-field">
        Notes
        <textarea
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          maxLength={NOTES_MAX_LENGTH}
          rows={3}
          required
          disabled={submitting}
          className="ag-textarea"
          placeholder="What was observed during the field check"
        />
        <span className="ag-hint">
          {notes.length}/{NOTES_MAX_LENGTH}
        </span>
      </label>

      <label className="ag-field">
        Write token (only if the server requires one)
        <input
          type="password"
          value={writeToken}
          onChange={(event) => setWriteToken(event.target.value)}
          autoComplete="off"
          disabled={submitting}
          className="ag-input"
        />
      </label>

      <div className="ag-formActions">
        <button type="submit" className="ag-button ag-buttonPrimary" disabled={submitting}>
          {submitting ? "Saving…" : "Record inspection"}
        </button>
      </div>

      {feedback && (
        <div role={feedback.kind === "error" ? "alert" : "status"} className={`ag-feedback ag-feedback_${feedback.kind}`}>
          <p>{feedback.text}</p>
          {feedback.code && <p className="ag-mono ag-small">{feedback.code}</p>}
        </div>
      )}

      <p className="ag-hint">
        Records are saved by the configured server store. Local development without a database uses temporary memory.
        Saving one does not change the cell&apos;s verification status.
      </p>
    </form>
  );
}
