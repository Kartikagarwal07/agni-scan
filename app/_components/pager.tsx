import { PAGE_SIZES } from "@/lib/dashboard/api";

type Props = {
  total: number;
  offset: number;
  limit: number;
  shown: number;
  onPage: (offset: number) => void;
  onLimit: (limit: number) => void;
};

/** Pagination for the API's limit/offset parameters. */
export function Pager({ total, offset, limit, shown, onPage, onLimit }: Props) {
  const last = Math.min(offset + shown, total);
  return (
    <div className="ag-pager">
      <span>{total === 0 ? "0 results" : `${offset + 1}–${last} of ${total}`}</span>
      <span>
        <label className="ag-inlineField">
          Per page
          <select
            value={limit}
            onChange={(event) => onLimit(Number(event.target.value))}
            className="ag-select ag-selectSmall"
          >
            {PAGE_SIZES.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          disabled={offset === 0}
          onClick={() => onPage(Math.max(0, offset - limit))}
          className="ag-button ag-buttonSmall"
        >
          Previous
        </button>
        <button
          type="button"
          disabled={last >= total}
          onClick={() => onPage(offset + limit)}
          className="ag-button ag-buttonSmall"
        >
          Next
        </button>
      </span>
    </div>
  );
}
