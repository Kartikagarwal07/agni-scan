import type { PriorityPage } from "@/lib/dashboard/api";
import { formatPercent, formatScore, VERIFICATION_LABEL } from "@/lib/dashboard/format";
import { Pager } from "./pager";
import { RiskBadge } from "./risk-badge";
import { EmptyState, ErrorState, Loading } from "./status";
import type { ApiState } from "./use-api";

type Props = {
  state: ApiState<PriorityPage>;
  selectedId: string | null;
  onSelect: (cellId: string) => void;
  onPage: (offset: number) => void;
  onLimit: (limit: number) => void;
  onRetry: () => void;
};

const COLUMNS = ["#", "Cell", "District", "Score", "Level", "Evidence", "Status"];

export function PriorityList({ state, selectedId, onSelect, onPage, onLimit, onRetry }: Props) {
  if (state.status === "idle" || state.status === "loading") return <Loading label="Loading verification priorities…" />;
  if (state.status === "error") return <ErrorState title="Could not load priorities" error={state.error} onRetry={onRetry} />;

  const { items, total, limit, offset } = state.data;
  if (items.length === 0) {
    return (
      <EmptyState title="No cells to prioritise">
        {total > 0 ? "This page is past the end of the list." : "No cells match the selected district."}
      </EmptyState>
    );
  }

  return (
    <div>
      <div className="ag-tableWrap">
        <table className="ag-table">
          <caption className="ag-srOnly">Cells ranked by verification priority</caption>
          <thead>
            <tr>
              {COLUMNS.map((column) => (
                <th key={column} scope="col">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((item, index) => {
              const selected = item.cell_id === selectedId;
              return (
                <tr key={item.cell_id} className={selected ? "ag-selectedRow" : undefined}>
                  <td className="ag-num ag-muted">{item.priority_rank ?? offset + index + 1}</td>
                  <td>
                    <button
                      type="button"
                      onClick={() => onSelect(item.cell_id)}
                      aria-pressed={selected}
                      className="ag-linkButton"
                    >
                      {item.cell_id}
                    </button>
                  </td>
                  <td>{item.district}</td>
                  <td className="ag-num">{formatScore(item.risk_score)}</td>
                  <td>
                    <RiskBadge level={item.risk_level} />
                  </td>
                  <td className="ag-num">{formatPercent(item.evidence_completeness)}</td>
                  <td>{VERIFICATION_LABEL[item.verification_status]}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <Pager total={total} offset={offset} limit={limit} shown={items.length} onPage={onPage} onLimit={onLimit} />
    </div>
  );
}
