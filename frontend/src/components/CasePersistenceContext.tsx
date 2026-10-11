/**
 * Phase 3.2 — cross-view state persistence for the Reviewer Portal.
 *
 * Arbitration is expensive (SSE stream + media analysis), so every completed
 * run is cached against its `case_id` and mirrored into `localStorage`. The
 * cache holds the whole decision record the UI needs to redraw a case
 * instantly:
 *
 *   • the full SSE event log (so the Agent Stream can replay without a network
 *     round trip)
 *   • telemetry facts and media findings (evidence packet + vision/audio state)
 *   • the Rider & Driver advocate arguments
 *   • the judge verdict, confidence score and escalation packet
 *
 * Switching cases or tabs therefore never re-runs the pipeline — only an
 * explicit "Re-run Arbitration" does that.
 *
 * The same provider owns the (mock) reviewer session, because the portal's
 * audit trail is keyed by the reviewer that signed off on a ticket.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import type {
  AgentEvent,
  ApprovalAccepted,
  CaseRunStatus,
  LoginAccepted,
  OverrideAccepted,
  ResolutionResult,
  ReviewerAction,
} from "@/types";
import { login as loginRequest } from "@/lib/api";

const STORE_KEY = "ryderesolve.case-store.v2";
const SESSION_KEY = "ryderesolve.session.v1";

/** Cap the replay log so a long session can never exhaust the 5 MB budget. */
const MAX_EVENTS = 400;

export interface CaseRecord {
  case_id: string;
  run_id: string | null;
  status: CaseRunStatus;
  /** Full SSE log — replayed verbatim when the case is revisited. */
  events: AgentEvent[];
  result: ResolutionResult | null;
  /** Closing entry once a reviewer approves or overrides the ticket. */
  review: ReviewerAction | null;
  error: string | null;
  updated_at: string;
}

type CaseStore = Record<string, CaseRecord>;

interface StoreApi {
  records: CaseStore;
  session: LoginAccepted | null;
  getRecord: (caseId: string) => CaseRecord | undefined;
  /** Mark tickets that are waiting for the background queue to pick them up. */
  markPending: (caseIds: string[]) => void;
  beginRun: (caseId: string, runId: string) => void;
  appendEvent: (caseId: string, event: AgentEvent) => void;
  completeRun: (caseId: string, result: ResolutionResult) => void;
  failRun: (caseId: string, message: string) => void;
  /** Explicit "Re-run Arbitration" — drops the cached decision for a case. */
  clearRun: (caseId: string) => void;
  reset: () => void;
  recordApproval: (caseId: string, approval: ApprovalAccepted, original: ResolutionResult | null, reviewerName: string) => void;
  recordOverride: (
    caseId: string,
    override: OverrideAccepted,
    original: ResolutionResult | null,
    reviewerId: string,
    reviewerName: string,
    note: string,
  ) => void;
  seedBaseline: (caseId: string, review: ReviewerAction) => void;
  signIn: (email: string, password: string) => Promise<LoginAccepted>;
  signOut: () => void;
  authPending: boolean;
  authError: string | null;
}

const StoreContext = createContext<StoreApi | null>(null);

// ---------------------------------------------------------------------------
// localStorage plumbing — every read/write is defensive so a corrupt or full
// quota can never take the portal down.
// ---------------------------------------------------------------------------

function readJSON<T>(key: string): T | null {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function writeJSON(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* quota exceeded or storage disabled — the in-memory cache still works */
  }
}

function loadStore(): CaseStore {
  const raw = readJSON<CaseStore>(STORE_KEY);
  if (!raw || typeof raw !== "object") return {};
  const clean: CaseStore = {};
  for (const [caseId, record] of Object.entries(raw)) {
    if (!record || typeof record !== "object") continue;
    clean[caseId] = {
      case_id: caseId,
      run_id: record.run_id ?? null,
      // A run that was mid-flight when the tab closed comes back as pending.
      status:
        record.status === "processing" || record.status === "pending"
          ? "idle"
          : record.status ?? "idle",
      events: Array.isArray(record.events) ? record.events : [],
      result: record.result ?? null,
      review: record.review ?? null,
      error: record.error ?? null,
      updated_at: record.updated_at ?? new Date().toISOString(),
    };
  }
  return clean;
}

function loadSession(): LoginAccepted | null {
  const raw = readJSON<LoginAccepted>(SESSION_KEY);
  if (!raw || typeof raw.token !== "string") return null;
  return raw;
}

function stamp(): string {
  return new Date().toISOString();
}

// ---------------------------------------------------------------------------

export function CasePersistenceProvider({ children }: { children: ReactNode }) {
  const [records, setRecords] = useState<CaseStore>(() => loadStore());
  const [session, setSession] = useState<LoginAccepted | null>(() => loadSession());
  const [authPending, setAuthPending] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  const recordsRef = useRef(records);
  useEffect(() => {
    recordsRef.current = records;
  }, [records]);

  // Mirror the cache (and the session) so a page refresh restores the board.
  useEffect(() => {
    writeJSON(STORE_KEY, records);
  }, [records]);

  useEffect(() => {
    if (session) writeJSON(SESSION_KEY, session);
    else
      try {
        window.localStorage.removeItem(SESSION_KEY);
      } catch {
        /* ignore */
      }
  }, [session]);

  const patch = useCallback((caseId: string, partial: Partial<CaseRecord>) => {
    setRecords((prev) => {
      const current = prev[caseId];
      const base: CaseRecord =
        current ??
        {
          case_id: caseId,
          run_id: null,
          status: "idle",
          events: [],
          result: null,
          review: null,
          error: null,
          updated_at: stamp(),
        };
      return { ...prev, [caseId]: { ...base, ...partial, updated_at: stamp() } };
    });
  }, []);

  const getRecord = useCallback((caseId: string) => recordsRef.current[caseId], []);

  const markPending = useCallback((caseIds: string[]) => {
    setRecords((prev) => {
      const next = { ...prev };
      for (const caseId of caseIds) {
        const existing = next[caseId];
        // Never downgrade a ticket that already has a decision or an audit trail.
        if (existing?.result || existing?.review) continue;
        next[caseId] = {
          case_id: caseId,
          run_id: existing?.run_id ?? null,
          status: "pending",
          events: existing?.events ?? [],
          result: existing?.result ?? null,
          review: existing?.review ?? null,
          error: null,
          updated_at: stamp(),
        };
      }
      return next;
    });
  }, []);

  const beginRun = useCallback(
    (caseId: string, runId: string) => {
      setRecords((prev) => ({
        ...prev,
        [caseId]: {
          case_id: caseId,
          run_id: runId,
          status: "processing",
          events: [],
          result: prev[caseId]?.result ?? null,
          review: prev[caseId]?.review ?? null,
          error: null,
          updated_at: stamp(),
        },
      }));
    },
    [],
  );

  const appendEvent = useCallback((caseId: string, event: AgentEvent) => {
    setRecords((prev) => {
      const current = prev[caseId];
      if (!current) return prev;
      const events = [...current.events, event];
      return {
        ...prev,
        [caseId]: {
          ...current,
          events: events.length > MAX_EVENTS ? events.slice(-MAX_EVENTS) : events,
          updated_at: stamp(),
        },
      };
    });
  }, []);

  const completeRun = useCallback((caseId: string, result: ResolutionResult) => {
    setRecords((prev) => ({
      ...prev,
      [caseId]: {
        case_id: caseId,
        run_id: result.run_id,
        status: result.status === "escalated" ? "escalated" : "resolved",
        events: prev[caseId]?.events ?? [],
        result,
        review: prev[caseId]?.review ?? null,
        error: null,
        updated_at: stamp(),
      },
    }));
  }, []);

  const failRun = useCallback(
    (caseId: string, message: string) => {
      patch(caseId, { status: "failed", error: message });
    },
    [patch],
  );

  const clearRun = useCallback((caseId: string) => {
    setRecords((prev) => {
      const existing = prev[caseId];
      const next = { ...prev };
      // A reviewer's audit trail survives a re-run; the decision does not.
      if (existing?.review) {
        next[caseId] = {
          ...existing,
          run_id: null,
          status: "idle",
          events: [],
          result: null,
          error: null,
          updated_at: stamp(),
        };
      } else {
        delete next[caseId];
      }
      return next;
    });
  }, []);

  const reset = useCallback(() => setRecords({}), []);

  const recordApproval = useCallback(
    (
      caseId: string,
      approval: ApprovalAccepted,
      original: ResolutionResult | null,
      reviewerName: string,
    ) => {
      patch(caseId, {
        status: "resolved",
        result: (() => {
          const base = recordsRef.current[caseId]?.result ?? original;
          if (!base) return base;
          return { ...base, approval };
        })(),
        review: {
          kind: "approved",
          reviewer_id: approval.reviewer_id,
          reviewer_name: reviewerName,
          note: approval.note,
          original_decision: original?.ruling?.decision ?? null,
          original_amount: original?.ruling?.amount ?? 0,
          final_decision: approval.decision ?? original?.ruling?.decision ?? "no_action",
          final_amount: approval.amount,
          at: approval.verified_at,
          knowledge_base_size: approval.knowledge_base_size,
        },
      });
    },
    [patch],
  );

  const recordOverride = useCallback(
    (
      caseId: string,
      override: OverrideAccepted,
      original: ResolutionResult | null,
      reviewerId: string,
      reviewerName: string,
      note: string,
    ) => {
      patch(caseId, {
        status: "resolved",
        result: (() => {
          const base = recordsRef.current[caseId]?.result ?? original;
          if (!base) return base;
          return { ...base, override };
        })(),
        review: {
          kind: "overridden",
          reviewer_id: reviewerId,
          reviewer_name: reviewerName,
          note,
          original_decision: override.previous_decision ?? original?.ruling?.decision ?? null,
          original_amount: original?.ruling?.amount ?? 0,
          final_decision: override.new_decision,
          final_amount: override.new_amount,
          at: new Date().toISOString(),
          knowledge_base_size: override.knowledge_base_size,
        },
      });
    },
    [patch],
  );

  const seedBaseline = useCallback(
    (caseId: string, review: ReviewerAction) => {
      const existing = recordsRef.current[caseId];
      if (existing?.review) return;
      patch(caseId, { status: "resolved", review });
    },
    [patch],
  );

  const signIn = useCallback(async (email: string, password: string) => {
    setAuthPending(true);
    setAuthError(null);
    try {
      const accepted = await loginRequest(email, password);
      setSession(accepted);
      return accepted;
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : String(err));
      throw err;
    } finally {
      setAuthPending(false);
    }
  }, []);

  const signOut = useCallback(() => setSession(null), []);

  const value = useMemo<StoreApi>(
    () => ({
      records,
      session,
      getRecord,
      markPending,
      beginRun,
      appendEvent,
      completeRun,
      failRun,
      clearRun,
      reset,
      recordApproval,
      recordOverride,
      seedBaseline,
      signIn,
      signOut,
      authPending,
      authError,
    }),
    [
      records,
      session,
      getRecord,
      markPending,
      beginRun,
      appendEvent,
      completeRun,
      failRun,
      clearRun,
      reset,
      recordApproval,
      recordOverride,
      seedBaseline,
      signIn,
      signOut,
      authPending,
      authError,
    ],
  );

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useCaseStore(): StoreApi {
  const ctx = useContext(StoreContext);
  if (!ctx) {
    throw new Error("useCaseStore must be used inside <CasePersistenceProvider>");
  }
  return ctx;
}

/** Convenience hook for the reviewer badge / sign-out control. */
export function useReviewerSession() {
  const { session, signOut } = useCaseStore();
  return { session, signOut };
}
