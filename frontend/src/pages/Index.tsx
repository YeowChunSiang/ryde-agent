import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AlertCircle, Archive, CheckCircle2, Cpu, Play, RotateCcw, Server, Unlock } from "lucide-react";

import type {
  AgentEvent,
  ApprovalAccepted,
  CaseSummary,
  Health,
  OverrideAccepted,
  PrecedentCase,
  ResolutionResult,
} from "@/types";
import {
  fetchCases,
  fetchHealth,
  fetchPrecedents,
  fetchResult,
  startDispute,
  subscribeToRun,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { toast } from "sonner";
import { CaseRail } from "@/components/CaseRail";
import { PipelineRail } from "@/components/PipelineRail";
import { AgentStream } from "@/components/AgentStream";
import { EvidencePanel } from "@/components/EvidencePanel";
import { AdvocatesPanel } from "@/components/AdvocatesPanel";
import { VerdictPanel } from "@/components/VerdictPanel";
import { RiskPanel } from "@/components/RiskPanel";
import { EscalationPanel } from "@/components/EscalationPanel";
import { ReviewerNav } from "@/components/ReviewerNav";
import { useCaseStore } from "@/components/CasePersistenceContext";
import { titleCase } from "@/components/agent-meta";
import { cn } from "@/lib/utils";

export default function Index() {
  const navigate = useNavigate();
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [result, setResult] = useState<ResolutionResult | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [tab, setTab] = useState("verdict");
  const [error, setError] = useState<string | null>(null);
  const [library, setLibrary] = useState<PrecedentCase[] | null>(null);
  const [params] = useSearchParams();

  const {
    records,
    session,
    beginRun,
    appendEvent,
    completeRun,
    failRun,
    recordApproval,
    recordOverride,
    reopenCase,
  } = useCaseStore();

  const cleanupRef = useRef<(() => void) | null>(null);
  const recordsRef = useRef(records);
  useEffect(() => {
    recordsRef.current = records;
  }, [records]);

  // --- auth gate ---------------------------------------------------------
  useEffect(() => {
    if (!session) navigate("/login", { replace: true });
  }, [session, navigate]);

  // --- bootstrap ---------------------------------------------------------
  useEffect(() => {
    if (!session) return;
    fetchHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
    fetchCases()
      .then((list) => {
        setCases(list);
        if (!list.length) return;
        // The reviewer board deep-links here with `?case=DISP-007`.
        const requested = params.get("case");
        const initial =
          (requested && list.find((c) => c.case_id === requested)?.case_id) ??
          list[1]?.case_id ??
          list[0].case_id;
        setSelected(initial);
      })
      .catch((err) => setError(String(err)));
    fetchPrecedents()
      .then((lib) => setLibrary(lib.precedents))
      .catch(() => setLibrary(null));

    return () => cleanupRef.current?.();
  }, [params, session]);

  /**
   * Phase 3.2 — restore a completed decision straight from the cache instead
   * of spending another arbitration round trip on it.
   */
  const restore = useCallback((caseId: string) => {
    const record = recordsRef.current[caseId];
    setEvents(record?.events ?? []);
    setResult(record?.result ?? null);
    setError(record?.error ?? null);
  }, []);

  useEffect(() => {
    if (selected) restore(selected);
    // `restore` is stable; re-running when the cache changes would clobber a
    // live stream, so this only reacts to case switches.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  // A human override writes a new precedent — refresh both the run result and
  // the knowledge base so the learning loop is visible immediately.
  const onOverridden = async (runId: string, override: OverrideAccepted, note: string) => {
    try {
      const [fresh, lib] = await Promise.all([fetchResult(runId), fetchPrecedents()]);
      setResult(fresh);
      setLibrary(lib.precedents);
      if (selected) {
        recordOverride(
          selected,
          override,
          recordsRef.current[selected]?.result ?? null,
          session?.reviewer_id ?? "reviewer-01",
          session?.name ?? "Reviewer",
          note,
        );
      }
    } catch (err) {
      setError(String(err));
    }
  };

  /** Phase 3.2 — reviewer confirms the ruling; the ticket closes and archives. */
  const onApproved = async (runId: string, approval: ApprovalAccepted) => {
    try {
      const [fresh, lib] = await Promise.all([fetchResult(runId), fetchPrecedents()]);
      setResult(fresh);
      setLibrary(lib.precedents);
      if (selected) {
        recordApproval(selected, approval, recordsRef.current[selected]?.result ?? null, session?.name ?? "Reviewer");
      }
    } catch (err) {
      setError(String(err));
    }
  };

  /** Re-open a closed ticket so the reviewer can approve or override again. */
  const onReopen = () => {
    if (!selected) return;
    const current = recordsRef.current[selected];
    reopenCase(selected);
    // Use the current record before clearing — the result is preserved by
    // reopenCase (only approval/override are nulled), so we can keep showing it.
    setResult(current?.result ?? null);
    setEvents(current?.events ?? []);
    setTab("verdict");
    toast.success(`Case ${selected} has been re-opened`, {
      description: "You can now re-run arbitration or override the previous ruling.",
    });
  };

  const activeCase = cases.find((c) => c.case_id === selected) ?? null;
  const activeRecord = selected ? records[selected] : undefined;
  const cached = Boolean(selected && records[selected]?.result);
  const reopened = activeRecord?.status === "reopened";
  // Phase 3.2: once a human reviewer has approved or overridden a ticket,
  // it is "archived". The cached result IS the version they signed off on —
  // we must never offer a re-run that would replace it with a new arbitration.
  // A re-opened ticket is NOT archived — the reviewer can re-run or override.
  const archived = Boolean(activeRecord?.review) && !reopened;
  const reviewedAt = activeRecord?.review?.at;
  const reviewedBy = activeRecord?.review?.reviewer_name;
  const reviewedKind = activeRecord?.review?.kind;
  const reviewedDateLabel = reviewedAt
    ? new Date(reviewedAt).toISOString().slice(0, 10)
    : null;

  if (!session) return null;

  // --- run arbitration ---------------------------------------------------
  const run = async () => {
    if (!selected) return;
    cleanupRef.current?.();
    setError(null);
    setEvents([]);
    setResult(null);
    setStreaming(true);
    setTab("evidence");

    try {
      const accepted = await startDispute(selected);
      beginRun(selected, accepted.run_id);
      cleanupRef.current = subscribeToRun(accepted.run_id, {
        onEvent: (data) => {
          const event = data as unknown as AgentEvent;
          setEvents((prev) => [...prev, event]);
          appendEvent(selected, event);
        },
        onEnd: async () => {
          setStreaming(false);
          setTab("verdict");
          try {
            const fresh = await fetchResult(accepted.run_id);
            setResult(fresh);
            completeRun(selected, fresh);
          } catch (err) {
            failRun(selected, String(err));
            setError(`Stream finished but result fetch failed: ${err}`);
          }
        },
        onError: () => setStreaming(false),
      });
    } catch (err) {
      setStreaming(false);
      if (selected) failRun(selected, String(err));
      setError(String(err));
    }
  };

  const selectCase = (caseId: string) => {
    if (streaming) return;
    cleanupRef.current?.();
    setSelected(caseId);
    setTab("verdict");
    restore(caseId);
  };

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      {/* ---------------- header ---------------- */}
      <header className="flex flex-wrap items-center gap-3 border-b border-border px-5 py-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary/15 text-primary">
            <Cpu className="h-4 w-4" />
          </div>
          <div>
            <h1 className="text-base font-bold leading-none tracking-tight">RYsolve</h1>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              Multi-agent autonomous dispute resolution
            </p>
          </div>
        </div>

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
                {library && (
                  <div className="flex items-center gap-2">
                    <span className="h-1.5 w-1.5 rounded-full bg-lime-400" />
                    <span className="text-xs">
                      KB: {library.length} precedents
                    </span>
                  </div>
                )}
                {health?.asr_engine && (
                  <div className="flex items-center gap-2">
                    <span className="h-1.5 w-1.5 rounded-full bg-sky-400" />
                    <span className="text-xs">
                      ASR: {health.asr_engine}
                    </span>
                  </div>
                )}
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
          <ReviewerNav />
          {reopened ? (
            <Badge
              variant="outline"
              className="h-8 gap-1.5 border-amber-500/40 bg-amber-500/10 px-2.5 font-mono text-[11px] text-amber-300"
              title="This case was manually re-opened. You can re-run arbitration or override the previous ruling."
            >
              <Unlock className="h-3.5 w-3.5" />
              Re-opened
            </Badge>
          ) : archived ? (
            <div className="flex items-center gap-2">
              <Badge
                variant="outline"
                className="h-8 gap-1.5 border-emerald-500/30 bg-emerald-500/10 px-2.5 font-mono text-[11px] text-emerald-300"
                title={`This case was closed by ${reviewedBy ?? "—"} on ${reviewedDateLabel ?? "—"}. The arbitration below is the version the reviewer signed off on.`}
              >
                {reviewedKind === "overridden" ? (
                  <Archive className="h-3.5 w-3.5" />
                ) : (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                )}
                {reviewedKind === "overridden" ? "Overridden" : "Approved"} by{" "}
                {reviewedBy ?? "—"}
                {reviewedDateLabel ? ` · ${reviewedDateLabel}` : ""}
              </Badge>
              <Button
                variant="outline"
                size="sm"
                className="h-8 gap-1.5 border-amber-500/40 text-amber-300"
                onClick={onReopen}
              >
                <Unlock className="h-3.5 w-3.5" />
                Reopen
              </Button>
            </div>
          ) : (
            <Button
              onClick={run}
              disabled={!selected || streaming}
              size="sm"
              className="h-8"
              title={
                archived
                  ? "This case has already been reviewed and is locked."
                  : undefined
              }
            >
              {cached && !streaming ? (
                <RotateCcw className="h-3.5 w-3.5" />
              ) : (
                <Play className="h-3.5 w-3.5" />
              )}
              {streaming ? "Arbitrating…" : cached ? "Re-run Arbitration" : "Run Arbitration"}
            </Button>
          )}
        </div>
      </header>

      {error && (
        <div className="flex items-center gap-2 border-b border-red-500/30 bg-red-500/10 px-5 py-2 text-sm text-red-300">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {/* ---------------- left rail ---------------- */}
        <aside className="shrink-0 border-b border-border lg:w-80 lg:border-b-0 lg:border-r">
          <div className="h-64 lg:h-full">
            <CaseRail
              cases={cases}
              selected={selected}
              onSelect={selectCase}
              disabled={streaming}
            />
          </div>
        </aside>

        {/* ---------------- main ---------------- */}
        <main className="flex min-h-0 flex-1 flex-col">
          <div className="border-b border-border px-5 py-3">
            {activeCase ? (
              <div className="mb-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs font-semibold">{activeCase.dispute_id}</span>
                  <Badge variant="outline" className="h-5 px-1.5 text-[10px] font-normal">
                    {titleCase(activeCase.dispute_type)}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    filed by {activeCase.filed_by}
                  </span>
                </div>
                <p className="mt-1 whitespace-normal break-words text-sm font-medium leading-relaxed">
                  {activeCase.title}
                </p>
              </div>
            ) : (
              <p className="mb-3 text-sm text-muted-foreground">Loading dispute queue…</p>
            )}
            <PipelineRail
              events={events}
              streaming={streaming}
              done={!streaming && Boolean(result)}
            />
          </div>

          <div className="flex min-h-0 flex-1 flex-col xl:flex-row">
            <section className="min-h-[22rem] flex-1 border-b border-border xl:border-b-0 xl:border-r">
              <div className="h-full">
                <AgentStream events={events} streaming={streaming} />
              </div>
            </section>

            <aside className="flex min-h-0 shrink-0 flex-col xl:w-[27rem]">
              <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
                <div className="border-b border-border px-4 py-2.5">
                  <TabsList className="grid w-full grid-cols-4">
                    <TabsTrigger value="evidence" className="px-1 text-[11px]">
                      Evidence
                    </TabsTrigger>
                    <TabsTrigger value="risk" className="px-1 text-[11px]">
                      Risk
                    </TabsTrigger>
                    <TabsTrigger value="arguments" className="px-1 text-[11px]">
                      Arguments
                    </TabsTrigger>
                    <TabsTrigger value="verdict" className="text-[11px]">
                      Verdict
                    </TabsTrigger>
                  </TabsList>
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto p-4">
                  <TabsContent value="evidence" className="mt-0">
                    <EvidencePanel
                      evidence={result?.evidence ?? null}
                      vision={result?.vision ?? []}
                      assets={activeCase?.evidence_assets ?? []}
                    />
                  </TabsContent>
                  <TabsContent value="risk" className="mt-0">
                    <RiskPanel
                      routing={result?.routing ?? null}
                      collection={result?.collection ?? null}
                      fraud={result?.fraud ?? null}
                      precedents={result?.precedents ?? null}
                      library={library}
                    />
                  </TabsContent>
                  <TabsContent value="arguments" className="mt-0">
                    <AdvocatesPanel
                      rider={result?.rider_argument ?? null}
                      driver={result?.driver_argument ?? null}
                    />
                  </TabsContent>
                  <TabsContent value="verdict" className="mt-0">
                    <VerdictPanel
                      result={result}
                      threshold={health?.escalation_threshold ?? 0.7}
                    />
                    <EscalationPanel
                      result={result}
                      onOverridden={onOverridden}
                      onApproved={onApproved}
                      reviewerId={session?.reviewer_id ?? "reviewer-01"}
                      reviewerName={session?.name ?? "Reviewer"}
                      token={session?.token}
                    />
                  </TabsContent>
                </div>
              </Tabs>
            </aside>
          </div>
        </main>
      </div>
    </div>
  );
}
