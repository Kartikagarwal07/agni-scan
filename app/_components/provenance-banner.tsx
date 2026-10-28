import type { Provenance } from "@/lib/dashboard/provenance";

const TONE = {
  synthetic: "ag-bannerSynthetic",
  observed: "",
  unknown: "ag-bannerUnknown",
} as const;

export function ProvenanceBanner({ provenance }: { provenance: Provenance }) {
  return (
    <section aria-label="Data provenance" className={`ag-banner ${TONE[provenance.kind]}`}>
      <p className="ag-bannerHeadline">
        {provenance.kind === "synthetic" && <span className="ag-demoTag">Demo</span>}
        {provenance.headline}
      </p>
      {provenance.disclaimer && <p>{provenance.disclaimer}</p>}
      {provenance.interpretation && <p className="ag-muted">{provenance.interpretation}</p>}
      <dl className="ag-meta">
        {provenance.source && (
          <div>
            <dt>Source label: </dt>
            <dd className="ag-mono">{provenance.source}</dd>
          </div>
        )}
        {provenance.analysisWindow && (
          <div>
            <dt>Analysis window (UTC): </dt>
            <dd>{provenance.analysisWindow}</dd>
          </div>
        )}
      </dl>
      {provenance.credits.length > 0 && (
        <div className="ag-credits">
          <p>Data credits</p>
          <ul>
            {provenance.credits.map((credit) => (
              <li key={credit}>{credit}</li>
            ))}
          </ul>
        </div>
      )}
      {provenance.notices.length > 0 && (
        <ul className="ag-notices">
          {provenance.notices.map((notice) => (
            <li key={notice}>{notice}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
