import { ImageIcon, Loader2 } from "lucide-react";

import type { CaseSummary } from "@/types";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { titleCase } from "./agent-meta";

interface Props {
  cases: CaseSummary[];
  selected: string | null;
  onSelect: (caseId: string) => void;
  disabled: boolean;
}

export function CaseRail({ cases, selected, onSelect, disabled }: Props) {
  return (
    <nav className="flex h-full min-h-0 flex-col">
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold tracking-tight">Dispute Queue</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {cases.length} sample dossiers · 3 categories
        </p>
      </div>

      <ul className="min-h-0 flex-1 overflow-y-auto p-2">
        {cases.map((c) => {
          const active = c.case_id === selected;
          return (
            <li key={c.case_id}>
              <button
                type="button"
                onClick={() => onSelect(c.case_id)}
                disabled={disabled}
                className={cn(
                  "mb-1.5 w-full rounded-md border px-3 py-2.5 text-left transition-colors",
                  "disabled:cursor-not-allowed disabled:opacity-60",
                  active
                    ? "border-primary/50 bg-primary/10"
                    : "border-border bg-card/40 hover:border-primary/30 hover:bg-card",
                )}
              >
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs font-semibold">{c.case_id}</span>
                  <Badge
                    variant="outline"
                    className="h-4 px-1 text-[10px] font-normal text-muted-foreground"
                  >
                    {titleCase(c.dispute_type)}
                  </Badge>
                  {c.multimodal && (
                    <ImageIcon className="h-3 w-3 shrink-0 text-fuchsia-400" aria-label="has media" />
                  )}
                </div>
                <p className="mt-1 text-xs font-medium leading-snug">{c.title}</p>
                <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
                  {c.blurb}
                </p>
                <p className="mt-1.5 text-[10px] uppercase tracking-wide text-emerald-400/80">
                  expected · {c.expected_ruling}
                </p>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export function RunningBadge({ active }: { active: boolean }) {
  if (!active) return null;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-emerald-400">
      <Loader2 className="h-3 w-3 animate-spin" />
      arbitrating
    </span>
  );
}
