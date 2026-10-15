import type {
  ApprovalAccepted,
  ApproveRequest,
  CaseSummary,
  DisputeAccepted,
  Health,
  LoginAccepted,
  MediaUploadResult,
  OverrideAccepted,
  OverrideRequest,
  PrecedentLibrary,
  ResolutionResult,
} from "@/types";

const BASE = "/api";

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} — ${path}`);
  }
  return (await res.json()) as T;
}

async function postJSON<T>(path: string, body: unknown, token?: string): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`POST ${path} failed: ${res.status} ${res.statusText} ${detail}`);
  }
  return (await res.json()) as T;
}

export async function fetchHealth(): Promise<Health> {
  return getJSON<Health>("/health");
}

export async function fetchCases(): Promise<CaseSummary[]> {
  const data = await getJSON<{ cases: CaseSummary[] }>("/cases");
  return data.cases;
}

export async function fetchCase(caseId: string): Promise<Record<string, unknown>> {
  return getJSON<Record<string, unknown>>(`/cases/${caseId}`);
}

export async function startDispute(caseId: string): Promise<DisputeAccepted> {
  const res = await fetch(`${BASE}/dispute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ case_id: caseId }),
  });
  if (!res.ok) {
    throw new Error(`Failed to start dispute: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as DisputeAccepted;
}

export async function fetchResult(runId: string): Promise<ResolutionResult> {
  return getJSON<ResolutionResult>(`/result/${runId}`);
}

/** Human reviewer correction — feeds the precedent knowledge base (learning loop). */
export async function submitOverride(
  runId: string,
  payload: OverrideRequest,
  token?: string,
): Promise<OverrideAccepted> {
  return postJSON<OverrideAccepted>(`/override/${runId}`, payload, token);
}

/**
 * Phase 3.2 — Reviewer Portal sign-in against the mock identity provider.
 * Rejects with a human-readable message on 401 so the login screen can render
 * it verbatim.
 */
export async function login(email: string, password: string): Promise<LoginAccepted> {
  const res = await fetch(`${BASE}/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (res.status === 401) {
    throw new Error("Invalid reviewer credentials.");
  }
  if (!res.ok) {
    throw new Error(`Sign-in failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as LoginAccepted;
}

/**
 * Phase 3.2 — reviewer confirms the agent ruling and closes the ticket.
 * Approving does *not* write a precedent: only corrections teach the system.
 */
export async function submitApproval(
  runId: string,
  payload: ApproveRequest,
  token?: string,
): Promise<ApprovalAccepted> {
  return postJSON<ApprovalAccepted>(`/approve/${runId}`, payload, token);
}

export async function fetchPrecedents(): Promise<PrecedentLibrary> {
  return getJSON<PrecedentLibrary>("/precedents");
}

/**
 * Phase 3: attach a multi-modal payload to a case *before* arbitration runs.
 * The backend parks it in the media store and grafts it onto the dossier when
 * `POST /dispute` loads the case, so the next run arbitrates the real file.
 */
export async function uploadMedia(
  kind: "audio" | "video",
  caseId: string,
  file: File,
  capturedAt?: string,
): Promise<MediaUploadResult> {
  const form = new FormData();
  form.append("file", file);
  form.append("case_id", caseId);
  if (capturedAt) form.append("captured_at", capturedAt);

  const res = await fetch(`${BASE}/upload-${kind}`, { method: "POST", body: form });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`Upload failed: ${res.status} ${res.statusText} ${detail}`);
  }
  return (await res.json()) as MediaUploadResult;
}

/** Count of payloads currently parked in the backend media store. */
export async function fetchUploads(): Promise<Record<string, unknown[]>> {
  return getJSON<Record<string, unknown[]>>("/media/uploads");
}

/**
 * Subscribe to the live inter-agent message stream for a run.
 * Returns a cleanup function that closes the EventSource.
 */
export function subscribeToRun(
  runId: string,
  handlers: {
    onEvent: (data: Record<string, unknown>) => void;
    onEnd?: () => void;
    onError?: (err: unknown) => void;
  },
): () => void {
  const source = new EventSource(`${BASE}/stream/${runId}`);

  // The orchestrator emits named events (info/evidence/argument/ruling/warning/error).
  const levels = ["info", "evidence", "argument", "ruling", "warning", "error"];
  for (const level of levels) {
    source.addEventListener(level, (evt) => {
      try {
        handlers.onEvent(JSON.parse((evt as MessageEvent).data));
      } catch {
        /* ignore unparseable frame */
      }
    });
  }

  source.addEventListener("end", () => {
    handlers.onEnd?.();
    source.close();
  });

  source.addEventListener("timeout", () => {
    handlers.onEnd?.();
    source.close();
  });

  source.onerror = (err) => {
    // EventSource fires onerror both on real failures and on normal stream close.
    handlers.onError?.(err);
    source.close();
  };

  return () => source.close();
}
