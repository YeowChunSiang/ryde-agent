import { Link, useNavigate } from "react-router-dom";
import { ArrowLeftRight, LogOut, ShieldCheck } from "lucide-react";

import { useCaseStore } from "@/components/CasePersistenceContext";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { titleCase } from "@/components/agent-meta";

/**
 * Phase 3.2 — the identity strip every portal view shares: reviewer badge on
 * the left, sign-out on the right. Renders nothing when nobody is signed in,
 * so the arbitration demo page stays usable without a session.
 */
export function ReviewerNav({ showBoardLink = true }: { showBoardLink?: boolean }) {
  const { session, signOut } = useCaseStore();
  const navigate = useNavigate();

  if (!session) return null;

  const onSignOut = () => {
    signOut();
    navigate("/login", { replace: true });
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span
        className="flex h-8 items-center gap-1.5 rounded-md border border-primary/30 bg-primary/10 px-2"
        title={`Signed in as ${session.reviewer_id}`}
      >
        <ShieldCheck className="h-3.5 w-3.5 text-primary" />
        <span className="text-xs font-medium leading-none">{session.name}</span>
        <span className="font-mono text-[10px] leading-none text-muted-foreground">
          {titleCase(session.role)}
        </span>
      </span>

      {showBoardLink && (
        <Button variant="ghost" size="sm" className="h-8 gap-1.5 px-2 text-xs" asChild>
          <Link to="/dashboard">
            <ArrowLeftRight className="h-3 w-3" />
            Reviewer board
          </Link>
        </Button>
      )}

      <Button
        variant="ghost"
        size="sm"
        className="h-8 gap-1.5 px-2 text-xs text-muted-foreground"
        onClick={onSignOut}
      >
        <LogOut className="h-3 w-3" />
        Sign out
      </Button>

      <Badge variant="outline" className="hidden h-6 font-mono text-[10px] lg:inline-flex">
        session {session.token.slice(0, 8)}
      </Badge>
    </div>
  );
}
