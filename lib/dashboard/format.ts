import type { InspectionResult, RiskLevel, VerificationStatus } from "@/lib/api-core";

export const INSPECTION_RESULT_LABEL: Record<InspectionResult, string> = {
  fire_evidence_found: "Fire evidence found",
  no_fire_evidence_found: "No fire evidence found",
  inconclusive: "Inconclusive",
};

/** "2026-10-26T14:30:00.000Z" -> "2026-10-26 14:30 UTC" (the API's timestamps are UTC). */
export function formatTimestamp(iso: string) {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(iso);
  return match ? `${match[1]} ${match[2]} UTC` : iso;
}

export const RISK_LABEL: Record<RiskLevel, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
  unknown: "Unknown",
};

export const VERIFICATION_LABEL: Record<VerificationStatus, string> = {
  unverified: "Unverified",
  scheduled: "Scheduled",
  verified_fire: "Verified: fire",
  verified_no_fire: "Verified: no fire",
};

/** A null score is missing evidence, never zero; render it as such. */
export function formatScore(score: number | null) {
  return score === null ? "No score" : String(Math.round(score));
}

export function formatPercent(fraction: number) {
  return `${Math.round(fraction * 100)}%`;
}

export function formatCount(n: number, singular: string, plural = `${singular}s`) {
  return `${n} ${n === 1 ? singular : plural}`;
}
