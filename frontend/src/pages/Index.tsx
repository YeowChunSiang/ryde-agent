import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AlertCircle, Archive, CheckCircle2, Cpu, Play, RotateCcw, Server } from "lucide-react";

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

  const activeCase = cases.find((c) => c.case_id === selected) ?? null;
  const activeRecord = selected ? records[selected] : undefined;
  const cached = Boolean(selected && records[selected]?.result);
  // Phase 3.2: once a human reviewer has approved or overridden a ticket,
  // it is "archived". The cached result IS the version they signed off on —
  // we must never offer a re-run that would replace it with a new arbitration.
  const archived = Boolean(activeRecord?.review);
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
            <h1 className="text-base font-bold leading-none tracking-tight">RydeResolve</h1>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              Multi-agent autonomous dispute resolution
            </p>
          </div>
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Badge
            variant="outline"
            className="h-6 gap-1.5 font-mono text-[10px]"
            title={
              health?.engine === "adp"
                ? "LLM reasoner: live Tencent Cloud ADP — set ADP_APP_KEY in backend/.env to enable."
                : "LLM reasoner: deterministic offline engine. Same ruling every run, no credential needed. Set ADP_APP_KEY to switch to live."
            }
          >
            <Server className="h-3 w-3" />
            {health ? `reasoner: ${health.engine}` : "reasoner: connecting…"}
          </Badge>
          {health && (
            <Badge
              variant="outline"
              className={
                health.adp_configured
                  ? "h-6 border-emerald-500/30 bg-emerald-500/10 font-mono text-[10px] text-emerald-300"
                  : "h-6 border-amber-500/30 bg-amber-500/10 font-mono text-[10px] text-amber-300"
              }
              title={
                health.adp_configured
                  ? "Tencent Cloud ADP credentials present — live LLM inference enabled."
                  : "Tencent Cloud ADP credentials are not set. The platform falls back to the deterministic offline reasoner so the demo always works."
              }
            >
              ADP: {health.adp_configured ? "connected" : "offline (offline reasoner)"}
            </Badge>
          )}
          {library && (
            <Badge
              variant="outline"
              className="h-6 border-lime-500/30 bg-lime-500/10 font-mono text-[10px] text-lime-300"
              title="Policy & Precedent knowledge base — grows every time a reviewer approves or overrides a ticket."
            >
              KB: {library.length} precedents
            </Badge>
          )}
          {health?.asr_engine && (
            <Badge
              variant="outline"
              className="h-6 border-sky-500/30 bg-sky-500/10 font-mono text-[10px] text-sky-300"
              title={
                health.asr_engine === "trtc"
                  ? "Audio transcripts come from live Tencent Cloud TRTC ASR."
                  : "Audio transcripts come from the deterministic offline simulator (set TRTC_SECRET_ID to switch to live)."
              }
            >
              ASR: {health.asr_engine}
            </Badge>
          )}
          {health?.video_backend && (
            <Badge
              variant="outline"
              className={
                health.video_backend === "unavailable"
                  ? "h-6 border-red-500/30 bg-red-500/10 font-mono text-[10px] text-red-300"
                  : "h-6 border-violet-500/30 bg-violet-500/10 font-mono text-[10px] text-violet-300"
              }
              title={
                health.video_backend === "unavailable"
                  ? "No video backend is installed on this host — install ffmpeg or opencv-python to enable keyframe extraction."
                  : health.video_backend === "opencv"
                    ? "Keyframes are extracted with OpenCV — used automatically when ffmpeg is not installed."
                    : "Keyframes are extracted with ffmpeg at 1 fps for the Judge and reviewer."
              }
            >
              keyframes: {health.video_backend}
            </Badge>
          )}
          <ReviewerNav />
          {archived ? (
            <Badge
              variant="outline"
              className="h-8 gap-1.5 border-emerald-500/30 bg-emerald-500/10 px-2.5 font-mono text-[11px] text-emerald-300"
              title={`This case was closed by ${reviewedBy ?? "—"} on ${reviewedDateLabel ?? "—"}. The arbitration below is the version the reviewer signed off on — it cannot be re-run.`}
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
                    <TabsTrigger value="evidence" className="px-1 text-xs">
                      Evidence
                    </TabsTrigger>
                    <TabsTrigger value="risk" className="px-1 text-xs">
                      Risk & RAG
                    </TabsTrigger>
                    <TabsTrigger value="arguments" className="px-1 text-xs">
                      Arguments
                    </TabsTrigger>
                    <TabsTrigger value="verdict" className="text-xs">
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
