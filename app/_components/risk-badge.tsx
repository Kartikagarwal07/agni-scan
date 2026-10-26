import type { RiskLevel } from "@/lib/api-core";
import { RISK_LABEL } from "@/lib/dashboard/format";

export function RiskBadge({ level }: { level: RiskLevel }) {
  return <span className={`ag-badge ag-badge_${level}`}>{RISK_LABEL[level]}</span>;
}
