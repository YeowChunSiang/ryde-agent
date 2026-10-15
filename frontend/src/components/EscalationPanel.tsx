import { useEffect, useState } from "react";
import { BookMarked, ClipboardList, Gavel, Loader2, ShieldCheck, UserCheck } from "lucide-react";

import type {
  ApprovalAccepted,
  Decision,
  OverrideAccepted,
  ResolutionResult,
} from "@/types";
import { submitApproval, submitOverride } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { DECISION_META, PRIORITY_META, titleCase } from "./agent-meta";
import { cn } from "@/lib/utils";

interface Props {
  result: ResolutionResult | null;
  /** Fired after `POST /override/{run_id}` succeeds. */
  onOverridden?: (runId: string, override: OverrideAccepted, note: string) => void;
  /** Fired after `POST /approve/{run_id}` succeeds. */
  onApproved?: (runId: string, approval: ApprovalAccepted) => void;
  /** Signed-in reviewer — falls back to the demo identity. */
  reviewerId?: string;
  reviewerName?: string;
  /** Reviewer session token — required for approve/override API calls. */
  token?: string;
  /** Render only the action row (used by the reviewer board). */
  actionsOnly?: boolean;
}

const HUMAN_DECISIONS: Decision[] = [
  "refund_rider",
  "partial_refund",
  "uphold_charge",
  "compensate_driver",
  "no_action",
];

/**
 * Human-in-the-loop surface: the escalation packet a reviewer receives, plus
 * the two ways to close a ticket.
 *
 * **Approve** (`POST /approve/{run_id}`) confirms the agent ruling, closes the
 * dispute and moves it to the History tab — it deliberately does *not* write a
 * precedent, because a confirmed ruling teaches the system nothing new.
 *
 * **Override** opens a modal that captures an alternative ruling plus the
 * reviewer's reasoning and submits it to `POST /override/{run_id}`, closing the
 * Learning Feedback Loop and incrementing the Precedent Knowledge Base.
 */
export function EscalationPanel({
  result,
  onOverridden,
  onApproved,
  reviewerId = "reviewer-01",
  reviewerName = "Reviewer",
  token,
  actionsOnly = false,
}: Props) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"approve" | "override" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [overrideOpen, setOverrideOpen] = useState(false);

  if (!result) return null;
  const packet = result.escalation;
  const ruling = result.ruling;

  const approve = async () => {
    setBusy("approve");
    setError(null);
    try {
      const accepted = await submitApproval(result.run_id, {
        reviewer_id: reviewerId,
        note: note.trim(),
      }, token);
      setNote("");
      onApproved?.(result.run_id, accepted);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(null);
    }
  };

  const closed = Boolean(result.approval || result.override);

  const actionRow = (
    <div className="grid gap-2">
      {!closed && (
        <label className="grid gap-1">
          <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
            Verification note (optional)
          </span>
          <Input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Signed off on the agent determination…"
            className="h-8 text-xs"
          />
        </label>
      )}

      {error && (
        <p className="whitespace-normal break-words text-xs leading-relaxed text-red-300">
          {error}
        </p>
      )}

      {closed ? (
        <p className="whitespace-normal break-words text-[11px] leading-relaxed text-muted-foreground">
          This ticket is closed and archived in the History tab.
        </p>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button
            onClick={approve}
            disabled={busy !== null}
            size="sm"
            className="h-8 flex-1 gap-1.5"
          >
            {busy === "approve" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <ShieldCheck className="h-3.5 w-3.5" />
            )}
            {busy === "approve" ? "Verifying…" : "Approve & close"}
          </Button>
          <Button
            onClick={() => setOverrideOpen(true)}
            disabled={busy !== null}
            size="sm"
            variant="outline"
            className="h-8 flex-1 gap-1.5 border-orange-500/40 text-orange-300"
          >
            <Gavel className="h-3.5 w-3.5" />
            Override ruling
          </Button>
        </div>
      )}

      <p className="whitespace-normal break-words text-[11px] leading-relaxed text-muted-foreground">
        {reviewerName} · {reviewerId}
      </p>
    </div>
  );

  if (actionsOnly) {
    return (
      <>
        {actionRow}
        <OverrideDialog
          open={overrideOpen}
          onOpenChange={setOverrideOpen}
          result={result}
          reviewerId={reviewerId}
          token={token}
          onSubmitted={(override, reasoning) => onOverridden?.(result.run_id, override, reasoning)}
        />
      </>
    );
  }

  if (!packet && !ruling?.escalated) return null;

  return (
    <div className="space-y-4 border-t border-border pt-4">
      {packet && (
        <section className="rounded-lg border border-orange-500/30 bg-orange-500/5 px-3 py-3">
          <h3 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-orange-300">
            <ClipboardList className="h-3.5 w-3.5" />
            Escalation Packet
          </h3>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Badge
              variant="outline"
              className={cn("h-5 px-1.5 text-[10px]", PRIORITY_META[packet.priority].className)}
            >
              {PRIORITY_META[packet.priority].label}
            </Badge>
            <span className="font-mono text-xs text-muted-foreground">
              routed to {packet.routed_to}
            </span>
            {packet.sla_due_at && (
              <span className="font-mono text-xs text-muted-foreground">
                due{" "}
                {new Date(packet.sla_due_at).toLocaleTimeString("en-GB", {
                  hour: "2-digit",
                  minute: "2-digit",
                  timeZone: "Asia/Singapore",
                })}
              </span>
            )}
          </div>
          <p className="mt-2 whitespace-normal break-words text-sm leading-relaxed text-foreground/90">
            {packet.case_summary}
          </p>

          {packet.evidence_digest.length > 0 && (
            <Bullets title="Evidence digest" items={packet.evidence_digest} />
          )}
          {packet.conflicting_points.length > 0 && (
            <Bullets title="Conflicting points" items={packet.conflicting_points} />
          )}
          {packet.risk_flags.length > 0 && (
            <Bullets title="Risk flags" items={packet.risk_flags} tone="warning" />
          )}
          {packet.recommended_focus.length > 0 && (
            <Bullets title="Recommended focus" items={packet.recommended_focus} />
          )}
          {packet.judge_recommendation && (
            <p className="mt-2 whitespace-normal break-words border-l-2 border-orange-500/40 pl-2 text-xs italic leading-relaxed text-muted-foreground">
              {packet.judge_recommendation}
            </p>
          )}
        </section>
      )}

      {/* ------------------ review actions ------------------ */}
      <section
        className={cn(
          "rounded-lg border px-3 py-3",
          result.approval
            ? "border-emerald-500/30 bg-emerald-500/5"
            : result.override
              ? "border-lime-500/30 bg-lime-500/5"
              : "border-border bg-card/50",
        )}
      >
        <h3
          className={cn(
            "flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider",
            result.approval
              ? "text-emerald-300"
              : result.override
                ? "text-lime-300"
                : "text-muted-foreground",
          )}
        >
          {result.approval ? (
            <ShieldCheck className="h-3.5 w-3.5" />
          ) : result.override ? (
            <BookMarked className="h-3.5 w-3.5" />
          ) : (
            <UserCheck className="h-3.5 w-3.5" />
          )}
          {result.approval
            ? "Human Verification Logged"
            : result.override
              ? "Learning Loop Closed"
              : "Reviewer Decision"}
        </h3>

        {result.approval && (
          <div className="mt-2">
            <p className="whitespace-normal break-words text-sm leading-relaxed">
              Ruling confirmed as{" "}
              <span className="font-semibold">
                {titleCase(result.approval.decision ?? "no_action")}
              </span>
              {result.approval.amount > 0 && (
                <span className="font-mono"> · S${result.approval.amount.toFixed(2)}</span>
              )}
              .
            </p>
            <p className="mt-1 whitespace-normal break-words text-xs leading-relaxed text-muted-foreground">
              Verified by {result.approval.reviewer_id} at{" "}
              {new Date(result.approval.verified_at).toLocaleTimeString("en-GB", {
                hour: "2-digit",
                minute: "2-digit",
                timeZone: "Asia/Singapore",
              })}
              . Knowledge base unchanged at {result.approval.knowledge_base_size} precedents —
              confirmed rulings do not teach the system.
            </p>
          </div>
        )}

        {result.override && (
          <div className="mt-2">
            <p className="whitespace-normal break-words text-sm leading-relaxed">
              Human decision{" "}
              <span className="font-semibold">
                {DECISION_META[result.override.new_decision].label}
              </span>
              {result.override.new_amount > 0 && (
                <span className="font-mono"> · S${result.override.new_amount.toFixed(2)}</span>
              )}{" "}
              stored as precedent{" "}
              <code className="font-mono text-xs">{result.override.precedent_id ?? "—"}</code>.
            </p>
            <p className="mt-1 whitespace-normal break-words text-xs leading-relaxed text-muted-foreground">
              Knowledge base now holds {result.override.knowledge_base_size} precedents — the
              next analogous dispute is judged against this ruling.
            </p>
          </div>
        )}

        <div className="mt-3">{actionRow}</div>
      </section>

      <OverrideDialog
        open={overrideOpen}
        onOpenChange={setOverrideOpen}
        result={result}
        reviewerId={reviewerId}
        token={token}
        onSubmitted={(override, reasoning) => onOverridden?.(result.run_id, override, reasoning)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------

/**
 * The Override modal shared by the case detail view and the reviewer board:
 * an alternative ruling + the reviewer's reasoning, posted to
 * `POST /override/{run_id}` so the correction lands in the knowledge base.
 */
export function OverrideDialog({
  open,
  onOpenChange,
  result,
  reviewerId,
  token,
  onSubmitted,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  result: ResolutionResult | null;
  reviewerId: string;
  token?: string;
  onSubmitted: (override: OverrideAccepted, note: string) => void;
}) {
  const [decision, setDecision] = useState<Decision>("partial_refund");
  const [amount, setAmount] = useState("0");
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Pre-fill the modal from the current ruling so a reviewer starts close to the
  // agent's number instead of from zero.
  useEffect(() => {
    if (!open || !result) return;
    setDecision(
      (result.ruling?.decision && result.ruling.decision !== "escalate_to_human"
        ? result.ruling.decision
        : "partial_refund") as Decision,
    );
    setAmount(String(result.ruling?.amount ?? 0));
    setRationale("");
    setError(null);
  }, [open, result]);

  if (!result) return null;

  const submit = async () => {
    if (!rationale.trim()) {
      setError("Human reasoning is required — it becomes the precedent's reviewer note.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const accepted = await submitOverride(result.run_id, {
        reviewer_id: reviewerId,
        decision,
        amount: Number(amount) || 0,
        rationale: rationale.trim(),
      }, token);
      onSubmitted(accepted, rationale.trim());
      onOpenChange(false);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-sm">
            <Gavel className="h-4 w-4 text-orange-300" />
            Override agent ruling
          </DialogTitle>
          <DialogDescription className="text-xs">
            {result.dispute_id} · the correction is written into the Policy &amp; Precedent
            knowledge base, so future disputes are judged against your reasoning.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3 py-1">
          {result.ruling && (
            <p className="whitespace-normal break-words rounded-md border border-border bg-muted/30 px-3 py-2 text-xs leading-relaxed text-muted-foreground">
              Agent verdict:{" "}
              <span className="font-semibold text-foreground">
                {DECISION_META[result.ruling.decision].label}
              </span>
              {result.ruling.amount > 0 && (
                <span className="font-mono"> · S${result.ruling.amount.toFixed(2)}</span>
              )}
              {result.ruling.confidence > 0 && (
                <span className="font-mono">
                  {" "}
                  · confidence {(result.ruling.confidence * 100).toFixed(0)}%
                </span>
              )}
            </p>
          )}

          <div className="grid grid-cols-2 gap-3">
            <label className="grid gap-1">
              <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                Alternative ruling
              </span>
              <select
                value={decision}
                onChange={(e) => setDecision(e.target.value as Decision)}
                className="h-9 rounded-md border border-border bg-background px-2 text-xs text-foreground"
              >
                {HUMAN_DECISIONS.map((d) => (
                  <option key={d} value={d}>
                    {DECISION_META[d].label}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1">
              <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                Amount (S$)
              </span>
              <Input
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                inputMode="decimal"
                className="h-9 font-mono text-xs"
              />
            </label>
          </div>

          <label className="grid gap-1">
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
              Human reasoning notes
            </span>
            <Textarea
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
              rows={4}
              placeholder="Why the agents got this wrong…"
              className="text-xs"
            />
          </label>

          {error && (
            <p className="whitespace-normal break-words text-xs leading-relaxed text-red-300">
              {error}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button size="sm" onClick={submit} disabled={busy} className="gap-1.5">
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Gavel className="h-3.5 w-3.5" />}
            {busy ? "Writing precedent…" : "Submit override"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Bullets({
  title,
  items,
  tone = "default",
}: {
  title: string;
  items: string[];
  tone?: "default" | "warning";
}) {
  return (
    <div className="mt-2">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{title}</p>
      <ul className="mt-1 space-y-0.5">
        {items.map((item, i) => (
          <li
            key={i}
            className={cn(
              "whitespace-normal break-words text-xs leading-relaxed",
              tone === "warning" ? "text-orange-300/90" : "text-foreground/80",
            )}
          >
            • {item}
          </li>
        ))}
      </ul>
    </div>
  );
}
