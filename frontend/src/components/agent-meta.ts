import type {
  AgentRole,
  Decision,
  EventLevel,
  RoutingStatus,
  SLAPriority,
  Support,
} from "@/types";

export interface AgentMeta {
  label: string;
  short: string;
  text: string;
  bg: string;
  border: string;
  dot: string;
}

export const AGENT_META: Record<AgentRole, AgentMeta> = {
  orchestrator: {
    label: "Orchestrator",
    short: "ORC",
    text: "text-zinc-300",
    bg: "bg-zinc-500/10",
    border: "border-zinc-500/30",
    dot: "bg-zinc-400",
  },
  sla_router: {
    label: "SLA & Routing Manager",
    short: "SLA",
    text: "text-rose-300",
    bg: "bg-rose-500/10",
    border: "border-rose-500/30",
    dot: "bg-rose-400",
  },
  evidence_collection: {
    label: "Evidence Collection Agent",
    short: "COL",
    text: "text-teal-300",
    bg: "bg-teal-500/10",
    border: "border-teal-500/30",
    dot: "bg-teal-400",
  },
  evidence: {
    label: "Evidence Engine",
    short: "EVD",
    text: "text-cyan-300",
    bg: "bg-cyan-500/10",
    border: "border-cyan-500/30",
    dot: "bg-cyan-400",
  },
  fraud: {
    label: "Fraud & Bad-Faith Agent",
    short: "FRD",
    text: "text-red-300",
    bg: "bg-red-500/10",
    border: "border-red-500/30",
    dot: "bg-red-400",
  },
  policy: {
    label: "Policy & Precedent Agent",
    short: "PRC",
    text: "text-indigo-300",
    bg: "bg-indigo-500/10",
    border: "border-indigo-500/30",
    dot: "bg-indigo-400",
  },
  learning: {
    label: "Learning Feedback Loop",
    short: "LRN",
    text: "text-lime-300",
    bg: "bg-lime-500/10",
    border: "border-lime-500/30",
    dot: "bg-lime-400",
  },
  vision: {
    label: "Image Analysis Agent",
    short: "VIS",
    text: "text-fuchsia-300",
    bg: "bg-fuchsia-500/10",
    border: "border-fuchsia-500/30",
    dot: "bg-fuchsia-400",
  },
  rider_advocate: {
    label: "Rider Advocate",
    short: "RAD",
    text: "text-blue-300",
    bg: "bg-blue-500/10",
    border: "border-blue-500/30",
    dot: "bg-blue-400",
  },
  driver_advocate: {
    label: "Driver Advocate",
    short: "DAD",
    text: "text-amber-300",
    bg: "bg-amber-500/10",
    border: "border-amber-500/30",
    dot: "bg-amber-400",
  },
  judge: {
    label: "Judge Agent",
    short: "JDG",
    text: "text-emerald-300",
    bg: "bg-emerald-500/10",
    border: "border-emerald-500/30",
    dot: "bg-emerald-400",
  },
  escalation: {
    label: "Escalation Gate",
    short: "ESC",
    text: "text-orange-300",
    bg: "bg-orange-500/10",
    border: "border-orange-500/30",
    dot: "bg-orange-400",
  },
};

export const PRIORITY_META: Record<SLAPriority, { label: string; className: string }> = {
  critical: { label: "CRITICAL", className: "bg-red-500/15 text-red-300 border-red-500/40" },
  high: { label: "HIGH", className: "bg-orange-500/15 text-orange-300 border-orange-500/40" },
  normal: { label: "NORMAL", className: "bg-zinc-500/15 text-zinc-300 border-zinc-500/40" },
  low: { label: "LOW", className: "bg-slate-500/15 text-slate-300 border-slate-500/40" },
};

export const ROUTING_META: Record<RoutingStatus, { label: string; className: string }> = {
  queued: { label: "queued", className: "bg-zinc-500/15 text-zinc-300 border-zinc-500/40" },
  fast_tracked: {
    label: "fast-tracked",
    className: "bg-rose-500/15 text-rose-300 border-rose-500/40",
  },
  in_arbitration: {
    label: "in arbitration",
    className: "bg-cyan-500/15 text-cyan-300 border-cyan-500/40",
  },
  auto_resolved: {
    label: "auto-resolved",
    className: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
  },
  escalated_to_human: {
    label: "escalated to human",
    className: "bg-orange-500/15 text-orange-300 border-orange-500/40",
  },
  overridden: {
    label: "human override",
    className: "bg-lime-500/15 text-lime-300 border-lime-500/40",
  },
};

export const FRAUD_VERDICT_META: Record<string, { label: string; className: string }> = {
  none: { label: "NO RISK", className: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40" },
  low: { label: "LOW", className: "bg-zinc-500/15 text-zinc-300 border-zinc-500/40" },
  suspected: {
    label: "SUSPECTED",
    className: "bg-orange-500/15 text-orange-300 border-orange-500/40",
  },
  likely: { label: "LIKELY", className: "bg-red-500/15 text-red-300 border-red-500/40" },
  confirmed: { label: "CONFIRMED", className: "bg-red-600/20 text-red-200 border-red-500/50" },
};

export const SUPPORT_META: Record<Support, { label: string; className: string }> = {
  rider: { label: "rider", className: "bg-blue-500/15 text-blue-300 border-blue-500/30" },
  driver: { label: "driver", className: "bg-amber-500/15 text-amber-300 border-amber-500/30" },
  neutral: { label: "neutral", className: "bg-zinc-500/15 text-zinc-300 border-zinc-500/30" },
};

export const DECISION_META: Record<
  Decision,
  { label: string; className: string; description: string }
> = {
  refund_rider: {
    label: "REFUND RIDER",
    className: "bg-blue-500/15 text-blue-300 border-blue-500/40",
    description: "Disputed amount returned to the rider in full.",
  },
  partial_refund: {
    label: "PARTIAL REFUND",
    className: "bg-violet-500/15 text-violet-300 border-violet-500/40",
    description: "Only the unjustified portion of the charge is returned.",
  },
  uphold_charge: {
    label: "CHARGE UPHELD",
    className: "bg-amber-500/15 text-amber-300 border-amber-500/40",
    description: "The charge stands — the driver met every policy obligation.",
  },
  compensate_driver: {
    label: "COMPENSATE DRIVER",
    className: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
    description: "The driver's claim is upheld and paid out.",
  },
  no_action: {
    label: "NO ACTION",
    className: "bg-zinc-500/15 text-zinc-300 border-zinc-500/40",
    description: "No money moves; the claim is dismissed.",
  },
  escalate_to_human: {
    label: "ESCALATED TO HUMAN",
    className: "bg-orange-500/15 text-orange-300 border-orange-500/40",
    description: "Confidence too low to rule autonomously — a human decides.",
  },
};

export const LEVEL_BORDER: Record<EventLevel, string> = {
  info: "border-l-zinc-600",
  evidence: "border-l-cyan-500",
  argument: "border-l-blue-500",
  ruling: "border-l-emerald-500",
  warning: "border-l-orange-500",
  error: "border-l-red-500",
};

export function formatDuration(ms: number | null | undefined): string | null {
  if (ms === null || ms === undefined) return null;
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "Asia/Singapore",
  });
}

export function titleCase(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
