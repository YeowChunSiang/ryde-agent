import { AlertTriangle, CheckCircle2, Gavel, Timer } from "lucide-react";

import type { ResolutionResult, Ruling } from "@/types";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { DECISION_META, formatDuration, titleCase } from "./agent-meta";
import { cn } from "@/lib/utils";

interface Props {
  result: ResolutionResult | null;
}

export function VerdictPanel({ result }: Props) {
  if (!result?.ruling) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-16 text-muted-foreground">
        <Gavel className="h-5 w-5" />
        <p className="text-sm">The judge has not ruled yet.</p>
      </div>
    );
  }

  const ruling = result.ruling as Ruling;
  const meta = DECISION_META[ruling.decision];
  const confidencePct = Math.round(ruling.confidence * 100);

  return (
    <div className="space-y-4">
      <div className={cn("rounded-lg border px-4 py-4", meta.className)}>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-lg font-bold tracking-tight">{meta.label}</span>
          {ruling.amount > 0 && (
            <span className="font-mono text-lg font-bold">S${ruling.amount.toFixed(2)}</span>
          )}
        </div>
        <p className="mt-1 text-xs opacity-80">{meta.description}</p>

        <div className="mt-4">
          <div className="flex items-center justify-between text-xs">
            <span className="font-medium">Confidence</span>
            <span className="font-mono">{confidencePct}%</span>
          </div>
          <Progress value={confidencePct} className="mt-1.5 h-1.5" />
          <p className="mt-1 text-[11px] text-muted-foreground">
            Autonomy threshold 65% — below it a human reviewer takes over.
          </p>
        </div>
      </div>

      {ruling.escalated && (
        <div className="flex items-start gap-2 rounded-lg border border-orange-500/30 bg-orange-500/5 px-4 py-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-orange-400" />
          <div>
            <p className="text-sm font-semibold text-orange-300">Escalated to a human reviewer</p>
            {ruling.escalation_reason && (
              <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                {ruling.escalation_reason}
              </p>
            )}
          </div>
        </div>
      )}

      <section>
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Reasoning
        </h3>
        <p className="mt-2 text-sm leading-relaxed text-foreground/90">{ruling.reasoning}</p>
      </section>

      {ruling.key_findings.length > 0 && (
        <section>
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Key Findings
          </h3>
          <ul className="mt-2 space-y-1">
            {ruling.key_findings.map((finding, i) => (
              <li key={i} className="flex gap-2 text-sm leading-relaxed">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
                <span>{finding}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {ruling.policy_applied.length > 0 && (
        <section>
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Policy Applied
          </h3>
          <div className="mt-2 flex flex-wrap gap-1">
            {ruling.policy_applied.map((ref) => (
              <code
                key={ref}
                className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground"
              >
                {ref}
              </code>
            ))}
          </div>
        </section>
      )}

      <section className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-border bg-card/50 px-3 py-2">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
            Message to rider
          </p>
          <p className="mt-1 text-sm leading-relaxed">{ruling.rider_summary}</p>
        </div>
        <div className="rounded-lg border border-border bg-card/50 px-3 py-2">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
            Message to driver
          </p>
          <p className="mt-1 text-sm leading-relaxed">{ruling.driver_summary}</p>
        </div>
      </section>

      <footer className="flex flex-wrap items-center gap-3 border-t border-border pt-3 text-xs text-muted-foreground">
        <Badge variant="outline" className="h-5 px-1.5 text-[10px]">
          {result.status === "escalated" ? "ESCALATED" : "RESOLVED"}
        </Badge>
        <span className="font-mono">engine: {result.engine}</span>
        {result.duration_ms !== null && (
          <span className="inline-flex items-center gap-1 font-mono">
            <Timer className="h-3 w-3" />
            {formatDuration(result.duration_ms)}
          </span>
        )}
        <span className="font-mono">{titleCase(result.dispute_type)}</span>
      </footer>
    </div>
  );
}
