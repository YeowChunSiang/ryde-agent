import { useMemo } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  Gavel,
  Loader2,
} from "lucide-react";

import type {
  CaseRunStatus,
  DisputeType,
  ReviewerAction,
  SLAPriority,
} from "@/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import {
  MEDIA_KIND_META,
  PRIORITY_META,
  QUEUE_PRIORITY_RANK,
  decisionLabel,
  priorityLabel,
  titleCase,
} from "@/components/agent-meta";

/** One row of the reviewer inbox — a case plus whatever the agents produced. */
export interface DisputeRow {
  case_id: string;
  dispute_id: string;
  dispute_type: DisputeType;
  title: string;
  filed_by: string;
  filed_at: string;
  financial_value: number;
  financial_note: string | null;
  evidence_kind: string | null;
  sla_priority: SLAPriority | null;
  queue: string | null;
  sla_due_at: string | null;
  status: CaseRunStatus;
  escalated: boolean;
  confidence: number | null;
  decision: string | null;
  amount: number;
  run_id: string | null;
  review: ReviewerAction | null;
}

interface Props {
  rows: DisputeRow[];
  mode?: "queue" | "history";
  empty?: string;
  /** Case ids with an in-flight approve/override call. */
  busy?: Record<string, boolean>;
  onReview?: (row: DisputeRow) => void;
  onApprove?: (row: DisputeRow) => void;
  onOverride?: (row: DisputeRow) => void;
}

/**
 * Phase 3.2 — the reviewer inbox.
 *
 * Rows are sorted the way the SLA & Routing Manager triages them: urgency rank
 * first (`CRITICAL` > `HIGH` > `MEDIUM` > `LOW`), then the money at stake.
 *
 * Extra queue guardrail: if a ticket sits 3 working days without a human
 * approve/override, aging bumps one band (`LOW -> MEDIUM`, `MEDIUM -> HIGH`)
 * so old low-priority work cannot be buried forever.
 *
 * Any ticket the Escalation Gate flagged carries a red warning badge.
 */
export function DisputeTable({
  rows,
  mode = "queue",
  empty = "Nothing to review.",
  busy = {},
  onReview,
  onApprove,
  onOverride,
}: Props) {
  const sorted = useMemo(() => {
    return [...rows].sort((a, b) => {
      const priorityA = effectiveQueuePriority(a);
      const priorityB = effectiveQueuePriority(b);
      const rankA = priorityA ? QUEUE_PRIORITY_RANK[priorityA] : 9;
      const rankB = priorityB ? QUEUE_PRIORITY_RANK[priorityB] : 9;
      if (rankA !== rankB) return rankA - rankB;
      // Secondary sort: financial exposure, highest first.
      if (b.financial_value !== a.financial_value) {
        return b.financial_value - a.financial_value;
      }
      return a.case_id.localeCompare(b.case_id);
    });
  }, [rows]);

  if (!rows.length) {
    return (
      <p className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-xs text-muted-foreground">
        {empty}
      </p>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="w-24 text-[10px] uppercase tracking-wider text-muted-foreground">
            Urgency
          </TableHead>
          <TableHead className="min-w-[16rem] text-[10px] uppercase tracking-wider text-muted-foreground">
            Case
          </TableHead>
          {mode === "queue" ? (
            <>
              <TableHead className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Evidence
              </TableHead>
              <TableHead className="text-right text-[10px] uppercase tracking-wider text-muted-foreground">
                Value
              </TableHead>
              <TableHead className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Agent status
              </TableHead>
              <TableHead className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Escalation
              </TableHead>
              <TableHead className="text-right text-[10px] uppercase tracking-wider text-muted-foreground">
                Action
              </TableHead>
            </>
          ) : (
            <>
              <TableHead className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Resolution status
              </TableHead>
              <TableHead className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Reviewer action
              </TableHead>
              <TableHead className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Original → final verdict
              </TableHead>
              <TableHead className="text-right text-[10px] uppercase tracking-wider text-muted-foreground">
                Closed at
              </TableHead>
            </>
          )}
        </TableRow>
      </TableHeader>

      <TableBody>
        {sorted.map((row) => (
          <TableRow
            key={row.case_id}
            className={cn(
              "align-top",
              row.escalated && mode === "queue" && "bg-red-500/[0.04]",
            )}
          >
            {/* ---- urgency ------------------------------------------------ */}
            <TableCell className="py-3">
              {(() => {
                const effective = effectiveQueuePriority(row);
                const aging = agingInfo(row);
                return (
                  <>
                    <Badge
                      variant="outline"
                      className={cn(
                        "h-5 px-1.5 text-[10px] font-semibold",
                        effective
                          ? PRIORITY_META[effective].className
                          : "border-zinc-500/40 bg-zinc-500/10 text-zinc-300",
                      )}
                    >
                      {priorityLabel(effective)}
                    </Badge>
                    {aging.bumped && (
                      <p className="mt-1 whitespace-normal text-[10px] leading-none text-amber-300">
                        aged +1 after {aging.workingDays} workdays
                      </p>
                    )}
                    {row.sla_due_at && (
                      <p className="mt-1 text-[10px] leading-none text-muted-foreground">
                        due{" "}
                        {new Date(row.sla_due_at).toLocaleTimeString("en-GB", {
                          hour: "2-digit",
                          minute: "2-digit",
                          timeZone: "Asia/Singapore",
                        })}
                      </p>
                    )}
                  </>
                );
              })()}
            </TableCell>

            {/* ---- case -------------------------------------------------- */}
            <TableCell className="py-3">
              {mode === "history" && onReview ? (
                <button
                  type="button"
                  onClick={() => onReview(row)}
                  className="w-full rounded-md border border-border/60 bg-card/30 px-2 py-1.5 text-left transition-colors hover:border-primary/40 hover:bg-card"
                  title="Open archived case for review"
                >
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-mono text-xs font-semibold">{row.case_id}</span>
                    <span className="font-mono text-[10px] text-muted-foreground">
                      {row.dispute_id}
                    </span>
                  </div>
                  <p className="mt-1 max-w-[22rem] whitespace-normal break-words text-xs font-medium leading-relaxed">
                    {row.title}
                  </p>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <Badge
                      variant="outline"
                      className="h-4 px-1 text-[10px] font-normal text-muted-foreground"
                    >
                      {titleCase(row.dispute_type)}
                    </Badge>
                    <span className="text-[10px] text-muted-foreground">
                      filed by {row.filed_by}
                    </span>
                    <span className="text-[10px] text-primary/80">click to review</span>
                  </div>
                </button>
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-mono text-xs font-semibold">{row.case_id}</span>
                    <span className="font-mono text-[10px] text-muted-foreground">
                      {row.dispute_id}
                    </span>
                  </div>
                  <p className="mt-1 max-w-[22rem] whitespace-normal break-words text-xs font-medium leading-relaxed">
                    {row.title}
                  </p>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <Badge
                      variant="outline"
                      className="h-4 px-1 text-[10px] font-normal text-muted-foreground"
                    >
                      {titleCase(row.dispute_type)}
                    </Badge>
                    <span className="text-[10px] text-muted-foreground">
                      filed by {row.filed_by}
                    </span>
                  </div>
                </>
              )}
            </TableCell>

            {mode === "queue" ? (
              <>
                {/* ---- evidence ------------------------------------------ */}
                <TableCell className="py-3">
                  {row.evidence_kind ? (
                    <Badge
                      variant="outline"
                      className={cn(
                        "h-5 px-1.5 text-[10px]",
                        MEDIA_KIND_META[row.evidence_kind]?.className,
                      )}
                    >
                      {MEDIA_KIND_META[row.evidence_kind]?.label ?? row.evidence_kind}
                    </Badge>
                  ) : (
                    <span className="text-[10px] text-muted-foreground">text only</span>
                  )}
                </TableCell>

                {/* ---- value --------------------------------------------- */}
                <TableCell className="py-3 text-right">
                  <span className="font-mono text-xs">
                    S${row.financial_value.toFixed(2)}
                  </span>
                  {row.financial_note && (
                    <p
                      className="mt-1 max-w-[9rem] whitespace-normal break-words text-[10px] leading-none text-muted-foreground"
                      title={row.financial_note}
                    >
                      {row.financial_note}
                    </p>
                  )}
                </TableCell>

                {/* ---- agent status -------------------------------------- */}
                <TableCell className="py-3">
                  <RunStatusPill status={row.status} confidence={row.confidence} />
                  {row.decision && (
                    <p className="mt-1 whitespace-normal break-words text-[10px] leading-none text-muted-foreground">
                      {decisionLabel(row.decision)}
                      {row.amount > 0 && (
                        <span className="font-mono"> · S${row.amount.toFixed(2)}</span>
                      )}
                    </p>
                  )}
                </TableCell>

                {/* ---- escalation ---------------------------------------- */}
                <TableCell className="py-3">
                  {row.escalated ? (
                    <Badge
                      variant="outline"
                      className="h-5 gap-1 border-red-500/50 bg-red-500/15 px-1.5 text-[10px] font-semibold text-red-300"
                    >
                      <AlertTriangle className="h-3 w-3" />
                      ESCALATED
                    </Badge>
                  ) : (
                    <span className="text-[10px] text-muted-foreground">—</span>
                  )}
                </TableCell>

                {/* ---- actions ------------------------------------------- */}
                <TableCell className="py-3">
                  <div className="flex flex-wrap items-center justify-end gap-1.5">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 gap-1 px-2 text-[11px]"
                      onClick={() => onReview?.(row)}
                      disabled={!row.run_id}
                    >
                      <ExternalLink className="h-3 w-3" />
                      Review
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-7 gap-1 px-2 text-[11px]"
                      onClick={() => onApprove?.(row)}
                      disabled={!row.run_id || busy[row.case_id]}
                    >
                      {busy[row.case_id] ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <CheckCircle2 className="h-3 w-3" />
                      )}
                      Approve
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 gap-1 px-2 text-[11px] text-orange-300"
                      onClick={() => onOverride?.(row)}
                      disabled={!row.run_id || busy[row.case_id]}
                    >
                      <Gavel className="h-3 w-3" />
                      Override
                    </Button>
                  </div>
                </TableCell>
              </>
            ) : (
              <>
                {/* ---- resolution status --------------------------------- */}
                <TableCell className="py-3">
                  {row.review?.kind === "overridden" ? (
                    <Badge
                      variant="outline"
                      className="h-5 border-lime-500/40 bg-lime-500/10 px-1.5 text-[10px] text-lime-300"
                    >
                      overridden
                    </Badge>
                  ) : row.review ? (
                    <Badge
                      variant="outline"
                      className="h-5 border-emerald-500/40 bg-emerald-500/10 px-1.5 text-[10px] text-emerald-300"
                    >
                      approved
                    </Badge>
                  ) : (
                    <Badge
                      variant="outline"
                      className="h-5 border-zinc-500/40 bg-zinc-500/10 px-1.5 text-[10px] text-zinc-300"
                    >
                      archived
                    </Badge>
                  )}
                  {row.escalated && (
                    <Badge
                      variant="outline"
                      className="mt-1 h-5 border-red-500/50 bg-red-500/15 px-1.5 text-[10px] text-red-300"
                    >
                      was escalated
                    </Badge>
                  )}
                </TableCell>

                {/* ---- reviewer action ----------------------------------- */}
                <TableCell className="py-3">
                  {row.review ? (
                    <>
                      <div className="flex items-center gap-1.5">
                        {row.review.kind === "overridden" ? (
                          <Gavel className="h-3 w-3 text-lime-300" />
                        ) : (
                          <CheckCircle2 className="h-3 w-3 text-emerald-300" />
                        )}
                        <span className="text-xs font-medium">
                          {row.review.kind === "overridden" ? "Override" : "Approved"}
                        </span>
                      </div>
                      <p className="mt-1 text-[10px] leading-none text-muted-foreground">
                        {row.review.reviewer_name || row.review.reviewer_id || "—"}
                      </p>
                      {row.review.note && (
                        <p className="mt-1 max-w-[18rem] whitespace-normal break-words text-[10px] leading-snug text-muted-foreground">
                          {row.review.note}
                        </p>
                      )}
                    </>
                  ) : (
                    <span className="text-[10px] text-muted-foreground">—</span>
                  )}
                </TableCell>

                {/* ---- original → final ---------------------------------- */}
                <TableCell className="py-3">
                  <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                    <span className="text-muted-foreground line-through">
                      {decisionLabel(row.review?.original_decision)}
                    </span>
                    <span className="text-muted-foreground">→</span>
                    <span className="font-semibold">
                      {decisionLabel(row.review?.final_decision ?? row.decision)}
                    </span>
                    {(row.review?.final_amount ?? row.amount) > 0 && (
                      <span className="font-mono text-[10px]">
                        S${(row.review?.final_amount ?? row.amount).toFixed(2)}
                      </span>
                    )}
                  </div>
                  {row.review?.kind === "overridden" && (
                    <p className="mt-1 text-[10px] leading-none text-lime-300/80">
                      precedent written · KB {row.review.knowledge_base_size}
                    </p>
                  )}
                </TableCell>

                {/* ---- closed at ----------------------------------------- */}
                <TableCell className="py-3 text-right">
                  {row.review?.at ? (
                    <>
                      <span className="font-mono text-[11px]">
                        {new Date(row.review.at).toLocaleDateString("en-GB", {
                          day: "2-digit",
                          month: "short",
                          timeZone: "Asia/Singapore",
                        })}
                      </span>
                      <p className="mt-1 font-mono text-[10px] leading-none text-muted-foreground">
                        {new Date(row.review.at).toLocaleTimeString("en-GB", {
                          hour: "2-digit",
                          minute: "2-digit",
                          timeZone: "Asia/Singapore",
                        })}
                      </p>
                    </>
                  ) : (
                    <span className="text-[10px] text-muted-foreground">—</span>
                  )}
                </TableCell>
              </>
            )}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

const SG_OFFSET_MS = 8 * 60 * 60 * 1000;

function toSingaporeDayStart(date: Date): Date {
  const shifted = new Date(date.getTime() + SG_OFFSET_MS);
  return new Date(Date.UTC(shifted.getUTCFullYear(), shifted.getUTCMonth(), shifted.getUTCDate()));
}

function workingDaysSince(iso: string): number {
  const started = new Date(iso);
  if (Number.isNaN(started.getTime())) return 0;
  const startDay = toSingaporeDayStart(started);
  const today = toSingaporeDayStart(new Date());
  if (today <= startDay) return 0;

  let days = 0;
  const cursor = new Date(startDay);
  while (cursor < today) {
    const weekday = cursor.getUTCDay();
    if (weekday >= 1 && weekday <= 5) days += 1;
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return days;
}

function agingInfo(row: DisputeRow): { workingDays: number; bumped: boolean } {
  if (row.review) return { workingDays: 0, bumped: false };
  if (!row.sla_priority || !row.filed_at) return { workingDays: 0, bumped: false };
  const workingDays = workingDaysSince(row.filed_at);
  if (workingDays < 3) return { workingDays, bumped: false };
  if (row.sla_priority === "low" || row.sla_priority === "normal") {
    return { workingDays, bumped: true };
  }
  return { workingDays, bumped: false };
}

function effectiveQueuePriority(row: DisputeRow): SLAPriority | null {
  if (!row.sla_priority) return null;
  const { bumped } = agingInfo(row);
  if (!bumped) return row.sla_priority;
  if (row.sla_priority === "low") return "normal";
  if (row.sla_priority === "normal") return "high";
  return row.sla_priority;
}

function RunStatusPill({
  status,
  confidence,
}: {
  status: CaseRunStatus;
  confidence: number | null;
}) {
  if (status === "processing") {
    return (
      <span className="inline-flex items-center gap-1.5 text-[11px] text-cyan-300">
        <Loader2 className="h-3 w-3 animate-spin" />
        arbitrating…
      </span>
    );
  }
  if (status === "pending") {
    return (
      <span className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <span className="h-1.5 w-1.5 rounded-full bg-zinc-500" />
        queued
      </span>
    );
  }
  if (status === "escalated") {
    return (
      <span className="inline-flex items-center gap-1.5 text-[11px] text-orange-300">
        <span className="h-1.5 w-1.5 rounded-full bg-orange-400" />
        escalated
      </span>
    );
  }
  if (status === "awaiting_review") {
    return (
      <span className="inline-flex items-center gap-1.5 text-[11px] text-sky-300">
        <span className="h-1.5 w-1.5 rounded-full bg-sky-400" />
        awaiting human review
        {confidence !== null && (
          <span className="font-mono text-[10px] text-muted-foreground">
            {(confidence * 100).toFixed(0)}%
          </span>
        )}
      </span>
    );
  }
  if (status === "resolved") {
    return (
      <span className="inline-flex items-center gap-1.5 text-[11px] text-emerald-300">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
        archived
      </span>
    );
  }
  if (status === "failed") {
    return <span className="text-[11px] text-red-300">run failed</span>;
  }
  return <span className="text-[11px] text-muted-foreground">not run</span>;
}
