import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  AlertCircle,
  AlertTriangle,
  BookMarked,
  ChevronDown,
  Cpu,
  Gavel,
  Loader2,
  RefreshCw,
  Server,
  ShieldCheck,
} from "lucide-react";

import type {
  AgentEvent,
  ApprovalAccepted,
  CaseSummary,
  Health,
  OverrideAccepted,
  ResolutionResult,
} from "@/types";
import {
  fetchCases,
  fetchHealth,
  fetchPrecedents,
  fetchResult,
  startDispute,
  submitApproval,
  subscribeToRun,
} from "@/lib/api";
import { useCaseStore } from "@/components/CasePersistenceContext";
import { DisputeTable, type DisputeRow, type SortMode } from "@/components/DisputeTable";
import { OverrideDialog } from "@/components/EscalationPanel";
import { ReviewerNav } from "@/components/ReviewerNav";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

/** How many arbitrations the background intake queue runs at once. */
const CONCURRENCY = 2;

/**
 * Phase 3.2 — the Reviewer Portal board.
 *
 * Landing here kicks off background arbitration for every incoming ticket that
 * has not been run yet (`pending` → `processing` → `awaiting_review` / `escalated`).
 * The queue is then ordered by SLA urgency and financial exposure, escalations
 * are hoisted into their own "Action Required" section, and closing a ticket
 * (Approve or Override) moves it to the History tab with a full audit trail.
 */
export default function Dashboard() {
  const navigate = useNavigate();
  const {
    session,
    records,
    markPending,
    beginRun,
    appendEvent,
    completeRun,
    failRun,
    clearRun,
    recordApproval,
    recordOverride,
    reopenCase,
    seedBaseline,
  } = useCaseStore();

  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [kbSize, setKbSize] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"queue" | "history">("queue");
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [overrideRow, setOverrideRow] = useState<DisputeRow | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [queueSort, setQueueSort] = useState<SortMode>("urgency");
  const [historySort, setHistorySort] = useState<SortMode>("newest");
  const [historyFilter, setHistoryFilter] = useState<string>("all");

  const recordsRef = useRef(records);
  useEffect(() => {
    recordsRef.current = records;
  }, [records]);

  const cleanupsRef = useRef<Record<string, (() => void) | undefined>>({});
  const autoStartedRef = useRef(false);
  const mountedRef = useRef(true);
  useEffect(() => () => {
    mountedRef.current = false;
    for (const cleanup of Object.values(cleanupsRef.current)) cleanup?.();
  }, []);

  // --- bootstrap ---------------------------------------------------------
  useEffect(() => {
    if (!session) {
      navigate("/login", { replace: true });
    }
  }, [session, navigate]);

  useEffect(() => {
    let alive = true;
    Promise.all([fetchCases(), fetchHealth(), fetchPrecedents()])
      .then(([list, h, lib]) => {
        if (!alive) return;
        setCases(list);
        setHealth(h);
        setKbSize(lib.count);
        setLoading(false);
      })
      .catch((err) => {
        if (!alive) return;
        setError(String(err));
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const refreshKb = useCallback(async () => {
    try {
      const lib = await fetchPrecedents();
      setKbSize(lib.count);
    } catch {
      /* non-fatal */
    }
  }, []);

  // Seed Archived with legacy tickets as reviewer-approved records so they use
  // the same audit language and timestamp semantics as normal human reviews.
  useEffect(() => {
    if (!cases.length || !session) return;
    for (const c of cases) {
      if (c.intake !== "historical") continue;
      seedBaseline(c.case_id, {
        kind: "approved",
        reviewer_id: session.reviewer_id,
        reviewer_name: session.name,
        note: `Approved by ${session.name}.`,
        original_decision: c.expected_ruling,
        original_amount: c.financial_value ?? 0,
        final_decision: c.expected_ruling,
        final_amount: c.financial_value ?? 0,
        at: new Date().toISOString(),
        knowledge_base_size: kbSize ?? 0,
      });
    }
  }, [cases, seedBaseline, kbSize, session]);

  // --- background arbitration -------------------------------------------
  const runOne = useCallback(
    async (caseId: string) => {
      try {
        const accepted = await startDispute(caseId);
        beginRun(caseId, accepted.run_id);
        await new Promise<void>((resolve) => {
          let settled = false;
          const done = () => {
            if (settled) return;
            settled = true;
            cleanupsRef.current[caseId]?.();
            delete cleanupsRef.current[caseId];
            resolve();
          };
          const cleanup = subscribeToRun(accepted.run_id, {
            onEvent: (data) => {
              if (mountedRef.current) appendEvent(caseId, data as unknown as AgentEvent);
            },
            onEnd: done,
            onError: done,
          });
          cleanupsRef.current[caseId] = cleanup;
        });
        const result = await fetchResult(accepted.run_id);
        if (mountedRef.current) completeRun(caseId, result);
      } catch (err) {
        if (mountedRef.current) failRun(caseId, String(err));
      }
    },
    [appendEvent, beginRun, completeRun, failRun],
  );

  const runQueue = useCallback(
    async (caseIds: string[]) => {
      let cursor = 0;
      const worker = async () => {
        while (cursor < caseIds.length && mountedRef.current) {
          const caseId = caseIds[cursor++];
          await runOne(caseId);
        }
      };
      await Promise.all(Array.from({ length: CONCURRENCY }, () => worker()));
    },
    [runOne],
  );

  useEffect(() => {
    if (!session || !cases.length || autoStartedRef.current) return;
    autoStartedRef.current = true;

    const todo = cases
      .filter((c) => {
        const rec = recordsRef.current[c.case_id];
        return !rec?.result && rec?.status !== "processing";
      })
      .map((c) => c.case_id);
    if (!todo.length) return;

    markPending(todo);
    void runQueue(todo);
  }, [session, cases, markPending, runQueue]);

  // --- review actions ----------------------------------------------------
  const reviewerId = session?.reviewer_id ?? "reviewer-01";
  const reviewerName = session?.name ?? "Reviewer";

  const onReview = useCallback(
    (row: DisputeRow) => navigate(`/review?case=${row.case_id}`),
    [navigate],
  );

  const onApprove = useCallback(
    async (row: DisputeRow) => {
      if (!row.run_id) return;
      setBusy((prev) => ({ ...prev, [row.case_id]: true }));
      try {
        const approval: ApprovalAccepted = await submitApproval(row.run_id, {
          reviewer_id: reviewerId,
          note: "Verified against the escalation packet and supporting evidence.",
        }, session?.token);
        const original = recordsRef.current[row.case_id]?.result ?? null;
        recordApproval(row.case_id, approval, original, reviewerName);
        await refreshKb();
        toast.success(`Case ${row.case_id} approved successfully`, {
          description: "It has been moved to the Archive tab.",
        });
        setTab("history");
      } catch (err) {
        setError(String(err));
      } finally {
        setBusy((prev) => ({ ...prev, [row.case_id]: false }));
      }
    },
    [recordApproval, refreshKb, reviewerId, reviewerName, session],
  );

  const onOverrideSubmit = useCallback(
    async (override: OverrideAccepted, note: string) => {
      const row = overrideRow;
      if (!row) return;
      const original = recordsRef.current[row.case_id]?.result ?? null;
      recordOverride(row.case_id, override, original, reviewerId, reviewerName, note);
      setOverrideRow(null);
      await refreshKb();
      toast.success(`Case ${row.case_id} override submitted successfully`, {
        description: "It has been moved to the Archive tab with the new verdict.",
      });
      setTab("history");
    },
    [overrideRow, recordOverride, refreshKb, reviewerId, reviewerName],
  );

  const onReopen = useCallback(
    (row: DisputeRow) => {
      reopenCase(row.case_id);
      toast.success(`Case ${row.case_id} has been re-opened`, {
        description: "Moved to the top of the New queue for further review.",
      });
      setTab("queue");
    },
    [reopenCase],
  );

  const reRunQueue = useCallback(async () => {
    const incoming = cases.filter((c) => c.intake === "incoming").map((c) => c.case_id);
    for (const caseId of incoming) clearRun(caseId);
    markPending(incoming);
    await runQueue(incoming);
  }, [cases, clearRun, markPending, runQueue]);

  // --- derived rows ------------------------------------------------------
  const rows = useMemo<DisputeRow[]>(
    () =>
      cases.map((c) => {
        const rec = records[c.case_id];
        const result: ResolutionResult | null = rec?.result ?? null;
        const escalated = Boolean(
          result?.ruling?.escalated || result?.status === "escalated" || rec?.status === "escalated",
        );
        return {
          case_id: c.case_id,
          dispute_id: c.dispute_id,
          dispute_type: c.dispute_type,
          title: c.title,
          filed_by: c.filed_by,
          filed_at: c.filed_at,
          financial_value: c.financial_value ?? 0,
          financial_note: c.financial_note ?? null,
          evidence_kind: c.evidence_kind ?? null,
          // Prioritisation is assigned only after arbitration has produced
          // routing output.
          sla_priority: result?.routing?.priority ?? null,
          queue: result?.routing?.queue ?? null,
          sla_due_at: result?.routing?.sla_due_at ?? null,
          status: rec?.status ?? "idle",
          escalated,
          confidence: result?.ruling?.confidence ?? null,
          decision: result?.ruling?.decision ?? null,
          amount: result?.ruling?.amount ?? 0,
          run_id: rec?.run_id ?? null,
          review: rec?.review ?? null,
        };
      }),
    [cases, records],
  );

  // Active rows: all incoming cases without a review, PLUS any case that was
  // manually reopened (status === "reopened") — regardless of original intake.
  const activeRows = rows.filter((r) => {
    if (r.status === "reopened") return true;
    const c = cases.find((x) => x.case_id === r.case_id);
    return c?.intake === "incoming" && !r.review;
  });
  const escalatedRows = activeRows.filter((r) => r.escalated || r.status === "escalated");
  // Reopened cases go to the top of the standard queue so they're acted on first.
  const standardRows = activeRows
    .filter((r) => !r.escalated && r.status !== "escalated")
    .sort((a, b) => {
      const aReopened = a.status === "reopened" ? 0 : 1;
      const bReopened = b.status === "reopened" ? 0 : 1;
      if (aReopened !== bReopened) return aReopened - bReopened;
      return 0; // preserve existing sort within groups
    });
  const historyRows = rows.filter(
    (r) =>
      r.review !== null ||
      (cases.find((x) => x.case_id === r.case_id)?.intake === "historical" &&
        r.status !== "reopened"),
  );

  // Collect unique reviewer names for the archive filter dropdown.
  const reviewerNames = useMemo(() => {
    const names = new Set<string>();
    historyRows.forEach((r) => {
      if (r.review?.reviewer_name) names.add(r.review.reviewer_name);
    });
    return Array.from(names).sort();
  }, [historyRows]);

  // Apply reviewer filter to history rows (sorting is handled by DisputeTable).
  const filteredHistoryRows = useMemo(() => {
    if (historyFilter === "all") return historyRows;
    return historyRows.filter((r) => r.review?.reviewer_name === historyFilter);
  }, [historyRows, historyFilter]);

  const running = rows.filter((r) => r.status === "processing").length;
  const pending = rows.filter((r) => r.status === "pending").length;
  const totalIncoming = cases.filter((c) => c.intake === "incoming").length;
  const progress = totalIncoming
    ? Math.round(((totalIncoming - running - pending) / totalIncoming) * 100)
    : 100;

  if (!session) return null;

  const overrideResult = overrideRow ? records[overrideRow.case_id]?.result ?? null : null;

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <header className="flex flex-wrap items-center gap-3 border-b border-border px-5 py-3">
        <Link to="/" className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary/15 text-primary">
            <Cpu className="h-4 w-4" />
          </div>
          <div>
            <h1 className="text-base font-bold leading-none tracking-tight">RydeResolve</h1>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              Human Reviewer Portal · SLA queue
            </p>
          </div>
        </Link>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" size="sm" className="h-8 gap-1.5 text-xs">
                <Server className="h-3.5 w-3.5" />
                System
                {health && !health.adp_configured && (
                  <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
                )}
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-80 p-3">
              <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                System Status
              </p>
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <Server className="h-3 w-3 shrink-0" />
                  <span className="text-xs">
                    {health ? `reasoner: ${health.engine}` : "reasoner: connecting…"}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "h-1.5 w-1.5 rounded-full",
                      health?.adp_configured ? "bg-emerald-400" : "bg-amber-400",
                    )}
                  />
                  <span className="text-xs">
                    {health ? `ADP: ${health.adp_configured ? "connected" : "offline (offline reasoner)"}` : "ADP: —"}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <BookMarked className="h-3 w-3 shrink-0" />
                  <span className="text-xs">
                    KB: {kbSize ?? "—"} precedents
                  </span>
                </div>
                {health?.video_backend && (
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        "h-1.5 w-1.5 rounded-full",
                        health.video_backend === "unavailable"
                          ? "bg-red-400"
                          : "bg-violet-400",
                      )}
                    />
                    <span className="text-xs">
                      keyframes: {health.video_backend}
                    </span>
                  </div>
                )}
              </div>
            </PopoverContent>
          </Popover>
          <Button
            variant="outline"
            size="sm"
            className="h-8 gap-1.5 text-xs"
            onClick={reRunQueue}
            disabled={running > 0}
          >
            {running > 0 ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            Re-run queue
          </Button>
          <ReviewerNav showBoardLink={false} />
        </div>
      </header>

      {error && (
        <div className="flex items-center gap-2 border-b border-red-500/30 bg-red-500/10 px-5 py-2 text-sm text-red-300">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      <main className="flex-1 px-5 py-4">
        {/* ---------------- stat strip ---------------- */}
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="Escalated to human"
            value={escalatedRows.length}
            tone="orange"
            icon={<AlertTriangle className="h-3.5 w-3.5" />}
          />
          <StatCard
            label="Critical priority"
            value={rows.filter((r) => r.sla_priority === "critical").length}
            tone="red"
          />
          <StatCard
            label="Awaiting review"
            value={standardRows.length}
            tone="zinc"
            icon={<ShieldCheck className="h-3.5 w-3.5" />}
          />
          <StatCard
            label="Closed & archived"
            value={historyRows.filter((r) => r.review).length}
            tone="emerald"
            icon={<Gavel className="h-3.5 w-3.5" />}
          />
        </div>

        {/* ---------------- intake progress ---------------- */}
        {(running > 0 || pending > 0) && (
          <div className="mt-3 rounded-lg border border-cyan-500/30 bg-cyan-500/5 px-3 py-2.5">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-cyan-300" />
              <span className="font-medium text-cyan-200">
                Background arbitration running — {running} processing, {pending} queued
              </span>
              <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                {progress}%
              </span>
            </div>
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-cyan-500/10">
              <div
                className="h-full rounded-full bg-cyan-400 transition-all duration-500"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}

        <Tabs value={tab} onValueChange={(v) => setTab(v as "queue" | "history")} className="mt-4">
          <TabsList className="grid w-full max-w-sm grid-cols-2">
            <TabsTrigger value="queue" className="text-xs">
              New ({activeRows.length})
            </TabsTrigger>
            <TabsTrigger value="history" className="text-xs">
              Archived ({historyRows.length})
            </TabsTrigger>
          </TabsList>

          <TabsContent value="queue" className="mt-4 space-y-5">
            <SortFilterBar
              sort={queueSort}
              onSortChange={setQueueSort}
              showReviewerFilter={false}
            />
            <section>
              <SectionHeader
                title="Action Required: Escalated Cases"
                hint="Escalation Gate flagged these — attend to them before any standard determination."
                tone="red"
                icon={<AlertTriangle className="h-3.5 w-3.5" />}
              />
              <DisputeTable
                rows={escalatedRows}
                busy={busy}
                sortMode={queueSort}
                onReview={onReview}
                onApprove={onApprove}
                onOverride={setOverrideRow}
                empty={
                  loading
                    ? "Loading dispute queue…"
                    : "No escalations pending — the queue is clean."
                }
              />
            </section>

            <Collapsible defaultOpen>
              <CollapsibleTrigger className="mb-2 w-full text-left">
                <SectionHeader
                  title="Standard Agent Determinations (Awaiting Review)"
                  hint="Agent-determined tickets awaiting human review, ordered by SLA urgency then financial exposure."
                  tone="zinc"
                  icon={<ShieldCheck className="h-3.5 w-3.5" />}
                  chevron
                />
              </CollapsibleTrigger>
              <CollapsibleContent>
                <DisputeTable
                  rows={standardRows}
                  busy={busy}
                  sortMode={queueSort}
                  onReview={onReview}
                  onApprove={onApprove}
                  onOverride={setOverrideRow}
                  empty={
                    loading ? "Loading dispute queue…" : "Every standard determination is closed."
                  }
                />
              </CollapsibleContent>
            </Collapsible>
          </TabsContent>

          <TabsContent value="history" className="mt-4">
            <SortFilterBar
              sort={historySort}
              onSortChange={setHistorySort}
              showReviewerFilter
              reviewerFilter={historyFilter}
              onReviewerFilterChange={setHistoryFilter}
              reviewerNames={reviewerNames}
            />
            <SectionHeader
              title="Archived — closed tickets & audit trail"
              hint="Resolution status, reviewer action, original vs final verdict and timestamp."
              tone="emerald"
              icon={<BookMarked className="h-3.5 w-3.5" />}
            />
            <DisputeTable
              rows={filteredHistoryRows}
              mode="history"
              busy={busy}
              sortMode={historySort}
              onReview={onReview}
              onReopen={onReopen}
              empty="Approve or override a ticket and it lands here with its full audit trail."
            />
          </TabsContent>
        </Tabs>
      </main>

      <OverrideDialog
        open={Boolean(overrideRow)}
        onOpenChange={(open) => !open && setOverrideRow(null)}
        result={overrideResult}
        reviewerId={reviewerId}
        token={session?.token}
        onSubmitted={onOverrideSubmit}
      />
    </div>
  );
}

function SortFilterBar({
  sort,
  onSortChange,
  showReviewerFilter,
  reviewerFilter,
  onReviewerFilterChange,
  reviewerNames,
}: {
  sort: SortMode;
  onSortChange: (v: SortMode) => void;
  showReviewerFilter: boolean;
  reviewerFilter?: string;
  onReviewerFilterChange?: (v: string) => void;
  reviewerNames?: string[];
}) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        Sort
      </span>
      <Select value={sort} onValueChange={(v) => onSortChange(v as SortMode)}>
        <SelectTrigger size="sm" className="h-7 w-[11rem] text-[11px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="urgency" className="text-[11px]">SLA urgency (default)</SelectItem>
          <SelectItem value="newest" className="text-[11px]">Newest first</SelectItem>
          <SelectItem value="oldest" className="text-[11px]">Oldest first</SelectItem>
        </SelectContent>
      </Select>
      {showReviewerFilter && (
        <>
          <span className="ml-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Reviewer
          </span>
          <Select
            value={reviewerFilter ?? "all"}
            onValueChange={(v) => onReviewerFilterChange?.(v)}
          >
            <SelectTrigger size="sm" className="h-7 w-[12rem] text-[11px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all" className="text-[11px]">All reviewers</SelectItem>
              {reviewerNames?.map((name) => (
                <SelectItem key={name} value={name} className="text-[11px]">
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  tone,
  icon,
}: {
  label: string;
  value: number;
  tone: "red" | "orange" | "zinc" | "emerald";
  icon?: React.ReactNode;
}) {
  const toneClass = {
    red: "border-red-500/30 bg-red-500/5 text-red-300",
    orange: "border-orange-500/30 bg-orange-500/5 text-orange-300",
    zinc: "border-border bg-card/50 text-foreground",
    emerald: "border-emerald-500/30 bg-emerald-500/5 text-emerald-300",
  }[tone];

  return (
    <div className={cn("flex items-center gap-3 rounded-lg border px-3 py-2", toneClass)}>
      {icon && <span className="shrink-0 opacity-80">{icon}</span>}
      <div>
        <p className="text-[10px] uppercase tracking-wider opacity-80">{label}</p>
        <p className="text-lg font-bold leading-none">{value}</p>
      </div>
    </div>
  );
}

function SectionHeader({
  title,
  hint,
  tone,
  icon,
  chevron = false,
}: {
  title: string;
  hint: string;
  tone: "red" | "zinc" | "emerald";
  icon?: React.ReactNode;
  chevron?: boolean;
}) {
  const toneClass = {
    red: "text-red-300",
    zinc: "text-foreground",
    emerald: "text-emerald-300",
  }[tone];

  return (
    <div className="mb-2">
      <h2 className={cn("flex items-center gap-1.5 text-sm font-semibold tracking-tight", toneClass)}>
        {icon}
        {title}
        {chevron && (
          <ChevronDown className="ml-auto h-3.5 w-3.5 text-muted-foreground transition-transform [[data-state=closed]_&]:rotate-180" />
        )}
      </h2>
      <p className="mt-0.5 whitespace-normal break-words text-[11px] leading-relaxed text-muted-foreground">
        {hint}
      </p>
    </div>
  );
}
