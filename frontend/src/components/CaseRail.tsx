import { useMemo } from "react";
import { CheckCircle2, ImageIcon, Loader2 } from "lucide-react";

import type { CaseSummary, SLAPriority } from "@/types";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { useCaseStore } from "@/components/CasePersistenceContext";
import { PRIORITY_META, QUEUE_PRIORITY_RANK, titleCase } from "./agent-meta";

interface Props {
  cases: CaseSummary[];
  selected: string | null;
  onSelect: (caseId: string) => void;
  disabled: boolean;
}

export function CaseRail({ cases, selected, onSelect, disabled }: Props) {
  const { records } = useCaseStore();
  const categories = new Set(cases.map((c) => c.dispute_type)).size;
  const cachedCount = cases.filter((c) => Boolean(records[c.case_id]?.result)).length;

  const queuePriorityOf = (caseId: string): SLAPriority | null => {
    const rec = records[caseId];
    return rec?.result?.routing?.priority ?? null;
  };

  const sortedCases = useMemo(() => {
    return [...cases].sort((a, b) => {
      const pa = queuePriorityOf(a.case_id);
      const pb = queuePriorityOf(b.case_id);
      const ra = pa ? QUEUE_PRIORITY_RANK[pa] : 9;
      const rb = pb ? QUEUE_PRIORITY_RANK[pb] : 9;
      if (ra !== rb) return ra - rb;
      const va = a.financial_value ?? 0;
      const vb = b.financial_value ?? 0;
      if (vb !== va) return vb - va;
      return a.case_id.localeCompare(b.case_id);
    });
  }, [cases, records]);

  return (
    <nav className="flex h-full min-h-0 flex-col">
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold tracking-tight">Dispute Queue</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {cases.length} sample dossiers · {categories} categories
        </p>
        <p className="mt-0.5 text-[10px] text-muted-foreground">
          sorted by post-arbitration priority, then value
        </p>
        <p className="mt-0.5 text-[10px] text-muted-foreground">
          {cachedCount} cached — restored instantly, no re-run
        </p>
      </div>

      <ul className="min-h-0 flex-1 overflow-y-auto p-2">
        {sortedCases.map((c) => {
          const active = c.case_id === selected;
          const cached = Boolean(records[c.case_id]?.result);
          const priority = queuePriorityOf(c.case_id);
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
                  {priority && (
                    <Badge
                      variant="outline"
                      className={cn(
                        "ml-auto h-4 px-1 text-[10px] font-semibold",
                        PRIORITY_META[priority].className,
                      )}
                    >
                      {PRIORITY_META[priority].label}
                    </Badge>
                  )}
                  {cached && (
                    <CheckCircle2
                      className="h-3 w-3 shrink-0 text-emerald-400"
                      aria-label="cached decision"
                    />
                  )}
                </div>
                <p className="mt-1 whitespace-normal break-words text-xs font-medium leading-relaxed">
                  {c.title}
                </p>
                <p className="mt-1 whitespace-normal break-words text-[11px] leading-relaxed text-muted-foreground">
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
