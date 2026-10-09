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
  | "sla_router"
  | "evidence_collection"
  | "evidence"
  | "fraud"
  | "policy"
  | "vision"
  | "rider_advocate"
  | "driver_advocate"
  | "judge"
  | "escalation"
  | "learning";

export type SLAPriority = "critical" | "high" | "normal" | "low";

export type RoutingStatus =
  | "queued"
  | "fast_tracked"
  | "in_arbitration"
  | "auto_resolved"
  | "escalated_to_human"
  | "overridden";

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

// --- Phase 2: SLA routing, ingestion, fraud, precedent, escalation ---------

export interface SLARoutingDecision {
  dispute_id: string;
  priority: SLAPriority;
  routing_status: RoutingStatus;
  fast_tracked: boolean;
  queue: string;
  queue_position: number;
  sla_target_minutes: number;
  sla_due_at: string;
  reasons: string[];
}

export interface CollectionRecord {
  source: string;
  endpoint: string;
  records: number;
  latency_ms: number;
  status: "ok" | "degraded" | "empty" | "failed";
  note: string | null;
}

export interface CollectionManifest {
  dispute_id: string;
  sources: CollectionRecord[];
  total_records: number;
  total_latency_ms: number;
  degraded: boolean;
  summary: string;
}

export interface FraudAssessment {
  dispute_id: string;
  risk_score: number;
  verdict: "none" | "low" | "suspected" | "likely" | "confirmed";
  rider_risk: number;
  driver_risk: number;
  signals: RiskSignal[];
  recommended_action: string;
  policy_refs: string[];
  reasoning: string;
}

export interface PrecedentCase {
  precedent_id: string;
  dispute_type: DisputeType;
  title: string;
  fact_signature: Record<string, unknown>;
  summary: string;
  ruling: string;
  amount: number;
  source: "seed" | "human_override";
  created_at: string;
  learned_from_run_id: string | null;
  reviewer_note: string | null;
}

export interface PrecedentMatch {
  precedent: PrecedentCase;
  similarity: number;
  matched_on: string[];
  recommendation: string;
}

export interface PrecedentBundle {
  dispute_id: string;
  matches: PrecedentMatch[];
  retrieved_count: number;
  consistency_note: string;
}

export interface EscalationPacket {
  run_id: string;
  dispute_id: string;
  priority: SLAPriority;
  queue: string;
  sla_due_at: string | null;
  routed_to: string;
  case_summary: string;
  evidence_digest: string[];
  conflicting_points: string[];
  risk_flags: string[];
  judge_recommendation: string;
  recommended_focus: string[];
}

export interface OverrideAccepted {
  run_id: string;
  dispute_id: string;
  status: "overridden";
  previous_decision: string | null;
  new_decision: Decision;
  new_amount: number;
  precedent_id: string | null;
  knowledge_base_size: number;
  message: string;
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
  routing: SLARoutingDecision | null;
  collection: CollectionManifest | null;
  evidence: EvidencePacket | null;
  fraud: FraudAssessment | null;
  precedents: PrecedentBundle | null;
  vision: VisionFinding[];
  rider_argument: AdvocateArgument | null;
  driver_argument: AdvocateArgument | null;
  ruling: Ruling | null;
  escalation: EscalationPacket | null;
  override: OverrideAccepted | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  errors: string[];
}

export interface OverrideRequest {
  reviewer_id: string;
  decision: Decision;
  amount: number;
  rationale: string;
}

export interface PrecedentLibrary {
  count: number;
  precedents: PrecedentCase[];
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
  { id: "intake", label: "Intake", agent: "orchestrator" },
  { id: "sla", label: "SLA Routing", agent: "sla_router" },
  { id: "evidence", label: "Evidence", agent: "evidence" },
  { id: "collection", label: "External Collection", agent: "evidence_collection" },
  { id: "risk", label: "Fraud & Precedent", agent: "fraud" },
  { id: "vision", label: "Image Analysis", agent: "vision" },
  { id: "advocacy", label: "Advocacy", agent: "rider_advocate" },
  { id: "arbitration", label: "Arbitration", agent: "judge" },
  { id: "escalation", label: "Escalation Gate", agent: "escalation" },
];

/** Map an emitted event `stage` onto a pipeline stage id. */
export function stageOf(stage: string): string {
  if (stage.startsWith("intake")) return "intake";
  if (stage.startsWith("sla") || stage.startsWith("routing")) return "sla";
  if (stage.startsWith("evidence") || stage === "risk_signal") return "evidence";
  // The parallel fan-out (collection + fraud + precedent) is dispatched from the
  // evidence stage and lands on the risk stage when the slowest branch returns.
  if (stage === "parallel_dispatch") return "evidence";
  if (stage.startsWith("parallel")) return "risk";
  if (stage.startsWith("collection")) return "collection";
  if (stage.startsWith("fraud") || stage.startsWith("precedent") || stage.startsWith("policy"))
    return "risk";
  if (stage.startsWith("vision")) return "vision";
  if (stage.startsWith("advocacy")) return "advocacy";
  if (stage.startsWith("arbitration") || stage.startsWith("ruling") || stage.startsWith("key_finding"))
    return "arbitration";
  if (stage.startsWith("escalation") || stage.startsWith("override")) return "escalation";
  if (stage === "pipeline_complete") return "escalation";
  return "intake";
}
