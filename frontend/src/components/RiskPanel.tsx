import { BookOpen, Database, Radar, Route, ShieldAlert } from "lucide-react";

import type {
  CollectionManifest,
  FraudAssessment,
  PrecedentBundle,
  PrecedentCase,
  SLARoutingDecision,
} from "@/types";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  FRAUD_VERDICT_META,
  PRIORITY_META,
  ROUTING_META,
  formatDuration,
  titleCase,
} from "./agent-meta";
import { cn } from "@/lib/utils";

interface Props {
  routing: SLARoutingDecision | null;
  collection: CollectionManifest | null;
  fraud: FraudAssessment | null;
  precedents: PrecedentBundle | null;
  library: PrecedentCase[] | null;
}

/**
 * Phase 2 context layer: how the ticket was routed, what external data was
 * ingested, how risky the parties look, and which past rulings the judge was
 * asked to stay consistent with.
 */
export function RiskPanel({ routing, collection, fraud, precedents, library }: Props) {
  if (!routing && !collection && !fraud && !precedents) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-16 text-muted-foreground">
        <Radar className="h-5 w-5" />
        <p className="text-sm">No routing or risk context yet.</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {routing && (
        <section>
          <SectionTitle icon={<Route className="h-3.5 w-3.5" />}>SLA & Routing</SectionTitle>
          <div className="mt-2 rounded-lg border border-border bg-card/50 px-3 py-2.5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge
                variant="outline"
                className={cn("h-5 px-1.5 text-[10px]", PRIORITY_META[routing.priority].className)}
              >
                {PRIORITY_META[routing.priority].label}
              </Badge>
              <Badge
                variant="outline"
                className={cn(
                  "h-5 px-1.5 text-[10px]",
                  ROUTING_META[routing.routing_status].className,
                )}
              >
                {ROUTING_META[routing.routing_status].label}
              </Badge>
              {routing.fast_tracked && (
                <Badge
                  variant="outline"
                  className="h-5 border-rose-500/40 bg-rose-500/10 px-1.5 text-[10px] text-rose-300"
                >
                  FAST-TRACKED
                </Badge>
              )}
            </div>
            <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
              <Row label="Queue" value={`${routing.queue} · #${routing.queue_position}`} />
              <Row label="SLA target" value={`${routing.sla_target_minutes} min`} />
              <Row
                label="Due"
                value={new Date(routing.sla_due_at).toLocaleTimeString("en-GB", {
                  hour: "2-digit",
                  minute: "2-digit",
                  timeZone: "Asia/Singapore",
                })}
              />
            </dl>
            {routing.reasons.length > 0 && (
              <ul className="mt-2 space-y-0.5">
                {routing.reasons.map((reason, i) => (
                  <li key={i} className="text-xs leading-relaxed text-muted-foreground">
                    • {reason}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      )}

      {collection && (
        <section>
          <SectionTitle icon={<Database className="h-3.5 w-3.5" />}>
            External Data Collection
          </SectionTitle>
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
            {collection.summary}
          </p>
          <ul className="mt-2 space-y-1.5">
            {collection.sources.map((src) => (
              <li
                key={src.endpoint}
                className={cn(
                  "rounded-md border px-3 py-2",
                  src.status === "ok"
                    ? "border-border bg-card/50"
                    : src.status === "failed"
                      ? "border-red-500/25 bg-red-500/5"
                      : "border-orange-500/25 bg-orange-500/5",
                )}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">{src.source}</span>
                  <Badge variant="outline" className="h-4 px-1 text-[10px]">
                    {src.status}
                  </Badge>
                  <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                    {src.records} rec · {formatDuration(src.latency_ms)}
                  </span>
                </div>
                <p className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground/70">
                  {src.endpoint}
                </p>
                {src.note && <p className="mt-0.5 text-xs text-muted-foreground">{src.note}</p>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {fraud && (
        <section>
          <SectionTitle icon={<ShieldAlert className="h-3.5 w-3.5" />}>
            Fraud & Bad-Faith Assessment
          </SectionTitle>
          <div className="mt-2 rounded-lg border border-border bg-card/50 px-3 py-2.5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge
                variant="outline"
                className={cn(
                  "h-5 px-1.5 text-[10px]",
                  FRAUD_VERDICT_META[fraud.verdict]?.className ??
                    "border-zinc-500/40 bg-zinc-500/10 text-zinc-300",
                )}
              >
                {FRAUD_VERDICT_META[fraud.verdict]?.label ?? fraud.verdict.toUpperCase()}
              </Badge>
              <span className="font-mono text-xs text-muted-foreground">
                risk {Math.round(fraud.risk_score * 100)}%
              </span>
            </div>
            <Progress value={Math.round(fraud.risk_score * 100)} className="mt-1.5 h-1.5" />
            <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
              <div>
                <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  Rider risk
                </p>
                <p className="font-mono">{Math.round(fraud.rider_risk * 100)}%</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  Driver risk
                </p>
                <p className="font-mono">{Math.round(fraud.driver_risk * 100)}%</p>
              </div>
            </div>
            <p className="mt-2 text-sm leading-relaxed text-foreground/90">{fraud.reasoning}</p>
            <p className="mt-1.5 text-xs text-muted-foreground">
              <span className="font-semibold">Action:</span> {fraud.recommended_action}
            </p>
            {fraud.policy_refs.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {fraud.policy_refs.map((ref) => (
                  <code
                    key={ref}
                    className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground"
                  >
                    {ref}
                  </code>
                ))}
              </div>
            )}
          </div>

          {fraud.signals.length > 0 && (
            <ul className="mt-2 space-y-1.5">
              {fraud.signals.map((signal, i) => (
                <li
                  key={`${signal.party}-${i}`}
                  className="rounded-md border border-border bg-card/50 px-3 py-2"
                >
                  <div className="flex items-center gap-2">
                    <Badge
                      variant="outline"
                      className={cn(
                        "h-4 px-1 text-[10px]",
                        signal.party === "rider"
                          ? "border-blue-500/30 bg-blue-500/15 text-blue-300"
                          : "border-amber-500/30 bg-amber-500/15 text-amber-300",
                      )}
                    >
                      {signal.party}
                    </Badge>
                    <span className="text-sm font-medium">{signal.signal}</span>
                    <Badge
                      variant="outline"
                      className={cn(
                        "ml-auto h-4 px-1 text-[10px]",
                        signal.severity === "high"
                          ? "border-red-500/30 bg-red-500/15 text-red-300"
                          : signal.severity === "medium"
                            ? "border-orange-500/30 bg-orange-500/15 text-orange-300"
                            : "border-zinc-500/30 bg-zinc-500/15 text-zinc-300",
                      )}
                    >
                      {signal.severity}
                    </Badge>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{signal.detail}</p>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {precedents && (
        <section>
          <SectionTitle icon={<BookOpen className="h-3.5 w-3.5" />}>
            Retrieved Precedents
          </SectionTitle>
          <p className="mt-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs leading-relaxed text-muted-foreground">
            {precedents.consistency_note}
          </p>
          {precedents.matches.length === 0 ? (
            <p className="mt-2 text-xs text-muted-foreground">
              No analogous rulings in the knowledge base — the judge rules on policy alone.
            </p>
          ) : (
            <ul className="mt-2 space-y-1.5">
              {precedents.matches.map((match) => (
                <li
                  key={match.precedent.precedent_id}
                  className="rounded-md border border-indigo-500/25 bg-indigo-500/5 px-3 py-2"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[10px] text-muted-foreground">
                      {match.precedent.precedent_id}
                    </span>
                    <span className="text-sm font-medium leading-snug">
                      {match.precedent.title}
                    </span>
                    <span className="ml-auto font-mono text-xs text-indigo-300">
                      {Math.round(match.similarity * 100)}% match
                    </span>
                  </div>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                    {match.precedent.summary}
                  </p>
                  <p className="mt-1 text-xs">
                    <span className="text-muted-foreground">Ruled: </span>
                    <span className="font-medium">{titleCase(match.precedent.ruling)}</span>
                    {match.precedent.amount > 0 && (
                      <span className="font-mono"> · S${match.precedent.amount.toFixed(2)}</span>
                    )}
                    {match.precedent.source === "human_override" && (
                      <Badge
                        variant="outline"
                        className="ml-1.5 h-4 border-lime-500/40 bg-lime-500/10 px-1 text-[10px] text-lime-300"
                      >
                        learned
                      </Badge>
                    )}
                  </p>
                  <p className="mt-1 border-l-2 border-indigo-500/40 pl-2 text-xs italic text-muted-foreground">
                    {match.recommendation}
                  </p>
                  {match.matched_on.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {match.matched_on.map((key) => (
                        <code
                          key={key}
                          className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground"
                        >
                          {key}
                        </code>
                      ))}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {library && library.length > 0 && (
        <section>
          <SectionTitle icon={<Database className="h-3.5 w-3.5" />}>
            Knowledge Base ({library.length})
          </SectionTitle>
          <ul className="mt-2 space-y-1">
            {library.map((p) => (
              <li
                key={p.precedent_id}
                className="flex items-start gap-2 rounded-md border border-border bg-card/40 px-2.5 py-1.5"
              >
                <span className="font-mono text-[10px] text-muted-foreground">
                  {p.precedent_id}
                </span>
                <span className="min-w-0 flex-1 truncate text-xs">{p.title}</span>
                {p.source === "human_override" && (
                  <Badge
                    variant="outline"
                    className="h-4 border-lime-500/40 bg-lime-500/10 px-1 text-[10px] text-lime-300"
                  >
                    review
                  </Badge>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-mono text-right">{value}</dd>
    </div>
  );
}

function SectionTitle({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <h3 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
      {icon}
      {children}
    </h3>
  );
}
