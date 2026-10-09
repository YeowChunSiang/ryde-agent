import { Check, Loader2 } from "lucide-react";

import { STAGES, type AgentEvent, stageOf } from "@/types";
import { AGENT_META } from "./agent-meta";
import { cn } from "@/lib/utils";

interface Props {
  events: AgentEvent[];
  streaming: boolean;
  done: boolean;
}

/**
 * Horizontal progress rail showing which stage of the deterministic state
 * pipeline is currently executing.
 */
export function PipelineRail({ events, streaming, done }: Props) {
  const reached = new Set(events.map((e) => stageOf(e.stage)));
  const lastStage = events.length ? stageOf(events[events.length - 1].stage) : null;

  return (
    <ol className="flex w-full flex-wrap items-center gap-x-1 gap-y-2">
      {STAGES.map((stage, i) => {
        const isReached = reached.has(stage.id);
        const isCurrent = streaming && lastStage === stage.id && !done;
        const meta = AGENT_META[stage.agent];

        return (
          <li key={stage.id} className="flex items-center gap-1">
            <div
              className={cn(
                "flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] transition-colors",
                isReached
                  ? cn(meta.border, meta.bg, meta.text)
                  : "border-border bg-card/40 text-muted-foreground",
                isCurrent && "ring-1 ring-primary/40",
              )}
            >
              {isCurrent ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : isReached ? (
                <Check className="h-3 w-3" />
              ) : (
                <span className="font-mono text-[10px] opacity-60">{i + 1}</span>
              )}
              <span className="font-medium">{stage.label}</span>
            </div>
            {i < STAGES.length - 1 && (
              <span
                className={cn(
                  "h-px w-3 sm:w-5",
                  isReached ? "bg-primary/40" : "bg-border",
                )}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}
