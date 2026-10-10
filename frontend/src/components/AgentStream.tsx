import { useEffect, useRef } from "react";
import { Radio } from "lucide-react";

import type { AgentEvent } from "@/types";
import { AGENT_META, LEVEL_BORDER, formatDuration, formatTime } from "./agent-meta";
import { cn } from "@/lib/utils";

interface Props {
  events: AgentEvent[];
  streaming: boolean;
}

/**
 * Live feed of inter-agent messages.
 *
 * This is the observability surface the Ryde problem statement asks for:
 * judges can watch each agent receive evidence, argue its case and hand off to
 * the next stage in real time.
 */
export function AgentStream({ events, streaming }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pinnedRef = useRef(true);

  // Keep the newest message in view unless the reader has scrolled up.
  useEffect(() => {
    if (pinnedRef.current && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [events.length]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <Radio
            className={cn(
              "h-4 w-4",
              streaming ? "animate-pulse text-emerald-400" : "text-muted-foreground",
            )}
          />
          <h2 className="text-sm font-semibold tracking-tight">Inter-Agent Communication</h2>
        </div>
        <span className="font-mono text-xs text-muted-foreground">
          {events.length} message{events.length === 1 ? "" : "s"}
          {streaming ? " · streaming" : ""}
        </span>
      </div>

      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="min-h-0 flex-1 overflow-y-auto px-4 py-3"
      >
        {events.length === 0 && (
          <div className="flex h-full items-center justify-center">
            <p className="max-w-xs text-center text-sm text-muted-foreground">
              Select a dispute and press <span className="font-medium text-foreground">Run Arbitration</span>{" "}
              to watch the agents deliberate.
            </p>
          </div>
        )}

        <ol className="space-y-2">
          {events.map((event) => {
            const meta = AGENT_META[event.agent];
            const duration = formatDuration(event.duration_ms);
            return (
              <li
                key={event.seq}
                className={cn(
                  "rounded-md border border-border border-l-2 bg-card/60 px-3 py-2 transition-colors",
                  LEVEL_BORDER[event.level],
                )}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <img
                    src={meta.avatar}
                    alt=""
                    width={22}
                    height={22}
                    loading="lazy"
                    className={cn(
                      "h-[22px] w-[22px] shrink-0 rounded-md border object-cover",
                      meta.border,
                      meta.bg,
                    )}
                    onError={(e) => {
                      // Fall back to the monogram chip if an avatar is missing.
                      e.currentTarget.style.display = "none";
                    }}
                  />
                  <span
                    className={cn(
                      "rounded border px-1.5 py-0.5 font-mono text-[10px] font-semibold tracking-wider",
                      meta.text,
                      meta.bg,
                      meta.border,
                    )}
                  >
                    {meta.short}
                  </span>
                  <span className={cn("text-xs font-medium", meta.text)}>{meta.label}</span>
                  <span className="font-mono text-[10px] text-muted-foreground">
                    {event.stage}
                  </span>
                  <span className="ml-auto flex items-center gap-2 font-mono text-[10px] text-muted-foreground">
                    {duration && <span>{duration}</span>}
                    <span>{formatTime(event.ts)}</span>
                  </span>
                </div>

                <p className="mt-1.5 text-sm leading-relaxed text-foreground/90">
                  {event.message}
                </p>

                {typeof event.payload?.claim === "string" && (
                  <p className="mt-1.5 border-l-2 border-border pl-2 text-xs italic leading-relaxed text-muted-foreground">
                    {event.payload.claim}
                  </p>
                )}
                {typeof event.payload?.reasoning === "string" && (
                  <p className="mt-1.5 border-l-2 border-border pl-2 text-xs italic leading-relaxed text-muted-foreground">
                    {event.payload.reasoning}
                  </p>
                )}
                {typeof event.payload?.summary === "string" &&
                  typeof event.payload?.claim !== "string" &&
                  typeof event.payload?.reasoning !== "string" && (
                    <p className="mt-1.5 border-l-2 border-border pl-2 text-xs italic text-muted-foreground">
                      {event.payload.summary}
                    </p>
                  )}
              </li>
            );
          })}
        </ol>
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
