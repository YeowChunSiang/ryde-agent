import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  AlertCircle,
  AlertTriangle,
  BookMarked,
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
import { DisputeTable, type DisputeRow } from "@/components/DisputeTable";
import { OverrideDialog } from "@/components/EscalationPanel";
import { ReviewerNav } from "@/components/ReviewerNav";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

/** How many arbitrations the background intake queue runs at once. */
const CONCURRENCY = 2;

/**
 * Phase 3.2 — the Reviewer Portal board.
 *
 * Landing here kicks off background arbitration for every incoming ticket that
 * has not been run yet (`pending` → `processing` → `resolved` / `escalated`).
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

  // Seed the History tab with the pre-automation tickets so the audit view is
  // never empty on a first visit.
  useEffect(() => {
    if (!cases.length) return;
    for (const c of cases) {
      if (c.intake !== "historical") continue;
      seedBaseline(c.case_id, {
        kind: "baseline",
        reviewer_id: "legacy-ops",
        reviewer_name: "Legacy ops desk",
        note: "Adjudicated before the agent platform — retained as the baseline verdict.",
        original_decision: null,
        original_amount: 0,
        final_decision: c.expected_ruling,
        final_amount: c.financial_value ?? 0,
        at: null,
        knowledge_base_size: kbSize ?? 0,
      });
    }
  }, [cases, seedBaseline, kbSize]);

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

    const incoming = cases.filter((c) => c.intake === "incoming").map((c) => c.case_id);
    const todo = incoming.filter((caseId) => {
      const rec = recordsRef.current[caseId];
      return !rec?.result && rec?.status !== "processing";
    });
    if (!todo.length) return;

    markPending(todo);
    void runQueue(todo);
  }, [session, cases, markPending, runQueue]);

  // --- review actions ----------------------------------------------------
  const reviewerId = session?.reviewer_id ?? "reviewer-01";
  const reviewerName = session?.name ?? "Reviewer";

  const onReview = useCallback(
    (row: DisputeRow) => navigate(`/?case=${row.case_id}`),
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
        });
        const original = recordsRef.current[row.case_id]?.result ?? null;
        recordApproval(row.case_id, approval, original, reviewerName);
        await refreshKb();
        setTab("history");
      } catch (err) {
        setError(String(err));
      } finally {
        setBusy((prev) => ({ ...prev, [row.case_id]: false }));
      }
    },
    [recordApproval, refreshKb, reviewerId, reviewerName],
  );

  const onOverrideSubmit = useCallback(
    async (override: OverrideAccepted, note: string) => {
      const row = overrideRow;
      if (!row) return;
      const original = recordsRef.current[row.case_id]?.result ?? null;
      recordOverride(row.case_id, override, original, reviewerId, reviewerName, note);
      setOverrideRow(null);
      await refreshKb();
      setTab("history");
    },
    [overrideRow, recordOverride, refreshKb, reviewerId, reviewerName],
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
          sla_priority: result?.routing?.priority ?? c.sla_priority ?? null,
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

  const activeRows = rows.filter((r) => {
    const c = cases.find((x) => x.case_id === r.case_id);
    return c?.intake === "incoming" && !r.review;
  });
  const escalatedRows = activeRows.filter((r) => r.escalated || r.status === "escalated");
  const standardRows = activeRows.filter((r) => !r.escalated && r.status !== "escalated");
  const historyRows = rows.filter(
    (r) => r.review !== null || cases.find((x) => x.case_id === r.case_id)?.intake === "historical",
  );

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
          <Badge variant="outline" className="h-6 gap-1.5 font-mono text-[10px]">
            <Server className="h-3 w-3" />
            {health ? `engine: ${health.engine}` : "connecting…"}
          </Badge>
          {kbSize !== null && (
            <Badge
              variant="outline"
              className="h-6 gap-1.5 border-lime-500/30 bg-lime-500/10 font-mono text-[10px] text-lime-300"
              title="Policy & Precedent knowledge base"
            >
              <BookMarked className="h-3 w-3" />
              KB: {kbSize}
            </Badge>
          )}
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
              Active Queue ({activeRows.length})
            </TabsTrigger>
            <TabsTrigger value="history" className="text-xs">
              History ({historyRows.length})
            </TabsTrigger>
          </TabsList>

          <TabsContent value="queue" className="mt-4 space-y-5">
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

            <section>
              <SectionHeader
                title="Standard Agent Determinations (Awaiting Review)"
                hint="Auto-resolved tickets, ordered by SLA urgency then financial exposure."
                tone="zinc"
                icon={<ShieldCheck className="h-3.5 w-3.5" />}
              />
              <DisputeTable
                rows={standardRows}
                busy={busy}
                onReview={onReview}
                onApprove={onApprove}
                onOverride={setOverrideRow}
                empty={
                  loading ? "Loading dispute queue…" : "Every standard determination is closed."
                }
              />
            </section>
          </TabsContent>

          <TabsContent value="history" className="mt-4">
            <SectionHeader
              title="History — closed tickets & audit trail"
              hint="Resolution status, reviewer action, original vs final verdict and timestamp."
              tone="emerald"
              icon={<BookMarked className="h-3.5 w-3.5" />}
            />
            <DisputeTable
              rows={historyRows}
              mode="history"
              busy={busy}
              onReview={onReview}
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
        onSubmitted={onOverrideSubmit}
      />
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
    <div className={cn("rounded-lg border px-3 py-2.5", toneClass)}>
      <p className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider opacity-80">
        {icon}
        {label}
      </p>
      <p className="mt-1 text-xl font-bold leading-none">{value}</p>
    </div>
  );
}

function SectionHeader({
  title,
  hint,
  tone,
  icon,
}: {
  title: string;
  hint: string;
  tone: "red" | "zinc" | "emerald";
  icon?: React.ReactNode;
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
      </h2>
      <p className="mt-0.5 whitespace-normal break-words text-[11px] leading-relaxed text-muted-foreground">
        {hint}
      </p>
    </div>
  );
}
