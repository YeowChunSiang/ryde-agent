import { Gavel, Scale } from "lucide-react";

import type { AdvocateArgument } from "@/types";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface Props {
  rider: AdvocateArgument | null;
  driver: AdvocateArgument | null;
}

/**
 * Side-by-side view of the two advocates. Both ran concurrently in the backend
 * via asyncio.gather — showing them together makes the adversarial structure
 * of the arbitration visible.
 */
export function AdvocatesPanel({ rider, driver }: Props) {
  if (!rider && !driver) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-16 text-muted-foreground">
        <Scale className="h-5 w-5" />
        <p className="text-sm">Advocates have not submitted yet.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {rider && <ArgumentCard argument={rider} party="rider" />}
      {driver && <ArgumentCard argument={driver} party="driver" />}
    </div>
  );
}

function ArgumentCard({
  argument,
  party,
}: {
  argument: AdvocateArgument;
  party: "rider" | "driver";
}) {
  const accent =
    party === "rider"
      ? "border-blue-500/30 bg-blue-500/5"
      : "border-amber-500/30 bg-amber-500/5";
  const chip =
    party === "rider"
      ? "border-blue-500/30 bg-blue-500/15 text-blue-300"
      : "border-amber-500/30 bg-amber-500/15 text-amber-300";

  return (
    <article className={cn("rounded-lg border px-4 py-3", accent)}>
      <header className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className={cn("h-5 px-1.5 text-[10px]", chip)}>
          {party === "rider" ? "RIDER ADVOCATE" : "DRIVER ADVOCATE"}
        </Badge>
        <span className="text-sm font-semibold leading-snug">{argument.headline}</span>
        <span className="ml-auto font-mono text-xs text-muted-foreground">
          confidence {(argument.confidence * 100).toFixed(0)}%
        </span>
      </header>

      <p className="mt-2 text-sm leading-relaxed text-foreground/90">{argument.claim}</p>

      <div className="mt-3 space-y-2">
        <Field label="Requested outcome">
          <span className="inline-flex items-center gap-1.5">
            <Gavel className="h-3.5 w-3.5 text-muted-foreground" />
            {argument.requested_outcome}
          </span>
        </Field>

        {argument.cited_facts.length > 0 && (
          <Field label="Cited facts">
            <span className="flex flex-wrap gap-1">
              {argument.cited_facts.map((key) => (
                <code
                  key={key}
                  className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground"
                >
                  {key}
                </code>
              ))}
            </span>
          </Field>
        )}

        {argument.policy_refs.length > 0 && (
          <Field label="Policy clauses">
            <span className="flex flex-wrap gap-1">
              {argument.policy_refs.map((ref, index) => (
                <code
                  key={`${ref}-${index}`}
                  className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground"
                >
                  {ref}
                </code>
              ))}
            </span>
          </Field>
        )}

        {argument.weaknesses.length > 0 && (
          <Field label="Declared weaknesses">
            <ul className="space-y-0.5">
              {argument.weaknesses.map((w, i) => (
                <li key={i} className="text-xs text-muted-foreground">
                  • {w}
                </li>
              ))}
            </ul>
          </Field>
        )}
      </div>
    </article>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[7.5rem_1fr] items-start gap-2">
      <span className="pt-0.5 text-[11px] uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <div className="text-sm leading-relaxed">{children}</div>
    </div>
  );
}
