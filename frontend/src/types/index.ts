/**
 * Wire types mirroring the FastAPI / Pydantic v2 contract in `backend/models.py`.
 * Kept in one place so the UI stays in sync with the arbitration pipeline.
 */

export type DisputeType =
  | "no_show_charge"
  | "route_deviation"
  | "property_damage"
  | "safety_incident"
  | "fare_dispute";

export type Support = "rider" | "driver" | "neutral";

export type AgentRole =
  | "orchestrator"
  | "evidence"
  | "vision"
  | "rider_advocate"
  | "driver_advocate"
  | "judge"
  | "escalation";

export type EventLevel =
  | "info"
  | "evidence"
  | "argument"
  | "ruling"
  | "warning"
  | "error";

export type Decision =
  | "refund_rider"
  | "partial_refund"
  | "uphold_charge"
  | "compensate_driver"
  | "no_action"
  | "escalate_to_human";

export interface CaseSummary {
  case_id: string;
  dispute_id: string;
  dispute_type: DisputeType;
  title: string;
  blurb: string;
  expected_ruling: string;
  filed_by: string;
  multimodal: boolean;
}

export interface Fact {
  key: string;
  label: string;
  value: string | number | boolean;
  unit: string | null;
  source: string;
  supports: Support;
  note: string | null;
}

export interface PolicyCheck {
  ref: string;
  description: string;
  expected: string;
  actual: string;
  compliant: boolean;
  supports: Support;
}

export interface RiskSignal {
  party: "rider" | "driver";
  signal: string;
  severity: "low" | "medium" | "high";
  detail: string;
}

export interface EvidencePacket {
  dispute_id: string;
  dispute_type: DisputeType;
  facts: Fact[];
  policy_checks: PolicyCheck[];
  risk_signals: RiskSignal[];
  summary: string;
}

export interface VisionFinding {
  attachment_id: string;
  genuine: boolean;
  authenticity_confidence: number;
  ai_generated_probability: number | null;
  exif_timestamp_delta_min: number | null;
  severity: string;
  anomalies: string[];
  reasoning: string;
}

export interface AdvocateArgument {
  agent: "rider_advocate" | "driver_advocate";
  headline: string;
  claim: string;
  cited_facts: string[];
  policy_refs: string[];
  requested_outcome: string;
  confidence: number;
  weaknesses: string[];
}

export interface Ruling {
  dispute_id: string;
  decision: Decision;
  amount: number;
  confidence: number;
  reasoning: string;
  key_findings: string[];
  policy_applied: string[];
  rider_summary: string;
  driver_summary: string;
  escalated: boolean;
  escalation_reason: string | null;
}

export interface AgentEvent {
  run_id: string;
  seq: number;
  ts: string;
  agent: AgentRole;
  stage: string;
  message: string;
  level: EventLevel;
  payload: Record<string, unknown>;
  duration_ms: number | null;
}

export interface ResolutionResult {
  run_id: string;
  dispute_id: string;
  dispute_type: DisputeType;
  status: "open" | "resolved" | "escalated";
  engine: "adp" | "offline";
  evidence: EvidencePacket | null;
  vision: VisionFinding[];
  rider_argument: AdvocateArgument | null;
  driver_argument: AdvocateArgument | null;
  ruling: Ruling | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  errors: string[];
}

export interface DisputeAccepted {
  run_id: string;
  dispute_id: string;
  dispute_type: DisputeType;
  stream_url: string;
  result_url: string;
  engine: "adp" | "offline";
}

export interface Health {
  status: string;
  service: string;
  engine: "adp" | "offline";
  adp_configured: boolean;
  escalation_threshold: number;
  runs: number;
}

/** Pipeline stages, in execution order — used for the progress rail. */
export const STAGES: { id: string; label: string; agent: AgentRole }[] = [
  { id: "intake", label: "Intake & Validation", agent: "orchestrator" },
  { id: "evidence", label: "Evidence Extraction", agent: "evidence" },
  { id: "vision", label: "Image Analysis", agent: "vision" },
  { id: "advocacy", label: "Parallel Advocacy", agent: "rider_advocate" },
  { id: "arbitration", label: "Arbitration", agent: "judge" },
  { id: "escalation", label: "Escalation Gate", agent: "escalation" },
];

/** Map an emitted event `stage` onto a pipeline stage id. */
export function stageOf(stage: string): string {
  if (stage.startsWith("intake")) return "intake";
  if (stage.startsWith("evidence") || stage.startsWith("policy") || stage.startsWith("risk"))
    return "evidence";
  if (stage.startsWith("vision")) return "vision";
  if (stage.startsWith("advocacy")) return "advocacy";
  if (stage.startsWith("arbitration") || stage.startsWith("ruling") || stage.startsWith("key_finding"))
    return "arbitration";
  if (stage.startsWith("escalation")) return "escalation";
  if (stage === "pipeline_complete") return "escalation";
  return "intake";
}
