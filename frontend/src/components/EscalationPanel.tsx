import { useState } from "react";
import { BookMarked, ClipboardList, Loader2, UserCheck } from "lucide-react";

import type { Decision, ResolutionResult } from "@/types";
import { submitOverride } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { DECISION_META, PRIORITY_META, titleCase } from "./agent-meta";
import { cn } from "@/lib/utils";

interface Props {
  result: ResolutionResult | null;
  onOverridden: (runId: string) => void;
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
 * the override form that writes the correction back into the precedent
 * knowledge base (learning feedback loop).
 */
export function EscalationPanel({ result, onOverridden }: Props) {
  const [reviewer, setReviewer] = useState("reviewer-01");
  const [decision, setDecision] = useState<Decision>("partial_refund");
  const [amount, setAmount] = useState("0");
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!result) return null;
  const packet = result.escalation;
  const ruling = result.ruling;
  if (!packet && !ruling?.escalated) return null;

  const submit = async () => {
    if (!rationale.trim()) {
      setError("A rationale is required — it becomes the precedent's reviewer note.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await submitOverride(result.run_id, {
        reviewer_id: reviewer.trim() || "reviewer-01",
        decision,
        amount: Number(amount) || 0,
        rationale: rationale.trim(),
      });
      onOverridden(result.run_id);
      setRationale("");
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

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
          <p className="mt-2 text-sm leading-relaxed text-foreground/90">{packet.case_summary}</p>

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
            <p className="mt-2 border-l-2 border-orange-500/40 pl-2 text-xs italic text-muted-foreground">
              {packet.judge_recommendation}
            </p>
          )}
        </section>
      )}

      {result.override ? (
        <section className="rounded-lg border border-lime-500/30 bg-lime-500/5 px-3 py-3">
          <h3 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-lime-300">
            <BookMarked className="h-3.5 w-3.5" />
            Learning Loop Closed
          </h3>
          <p className="mt-2 text-sm leading-relaxed">
            Human decision <span className="font-semibold">{DECISION_META[result.override.new_decision].label}</span>
            {result.override.new_amount > 0 && (
              <span className="font-mono"> · S${result.override.new_amount.toFixed(2)}</span>
            )}{" "}
            stored as precedent{" "}
            <code className="font-mono text-xs">{result.override.precedent_id ?? "—"}</code>.
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Knowledge base now holds {result.override.knowledge_base_size} precedents — the next
            analogous dispute is judged against this ruling.
          </p>
        </section>
      ) : (
        <section className="rounded-lg border border-border bg-card/50 px-3 py-3">
          <h3 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            <UserCheck className="h-3.5 w-3.5" />
            Human Override
          </h3>

          <div className="mt-3 grid gap-2">
            <label className="grid gap-1">
              <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                Reviewer
              </span>
              <Input
                value={reviewer}
                onChange={(e) => setReviewer(e.target.value)}
                className="h-8 font-mono text-xs"
              />
            </label>

            <div className="grid grid-cols-2 gap-2">
              <label className="grid gap-1">
                <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  Decision
                </span>
                <select
                  value={decision}
                  onChange={(e) => setDecision(e.target.value as Decision)}
                  className="h-8 rounded-md border border-border bg-background px-2 text-xs text-foreground"
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
                  className="h-8 font-mono text-xs"
                />
              </label>
            </div>

            <label className="grid gap-1">
              <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                Rationale (becomes the precedent note)
              </span>
              <Textarea
                value={rationale}
                onChange={(e) => setRationale(e.target.value)}
                rows={3}
                placeholder="Why the judge got it wrong…"
                className="text-xs"
              />
            </label>

            {error && <p className="text-xs text-red-300">{error}</p>}

            <Button onClick={submit} disabled={busy} size="sm" className="h-8 w-full">
              {busy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <UserCheck className="h-3.5 w-3.5" />
              )}
              {busy ? "Writing precedent…" : "Submit override & teach the system"}
            </Button>
            <p className="text-[11px] text-muted-foreground">
              Overriding replaces the {ruling ? titleCase(ruling.decision) : "judge"} ruling and
              injects your decision into the Policy &amp; Precedent knowledge base.
            </p>
          </div>
        </section>
      )}
    </div>
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
              "text-xs leading-relaxed",
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
