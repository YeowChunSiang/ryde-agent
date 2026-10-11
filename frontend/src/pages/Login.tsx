import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertCircle, ArrowRight, Cpu, Loader2, ShieldCheck } from "lucide-react";

import { useCaseStore } from "@/components/CasePersistenceContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/**
 * Phase 3.2 — Human Reviewer Portal sign-in.
 *
 * Credentials are checked by `POST /login` against the seeded reviewer account.
 * The reviewer session is in-memory only, so a fresh reload always returns to
 * this page for an explicit sign-in.
 */
export default function Login() {
  const navigate = useNavigate();
  const { session, signIn, authPending, authError } = useCaseStore();
  const [email, setEmail] = useState("reviewer@ryde.com");
  const [password, setPassword] = useState("admin2026");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (session) navigate("/dashboard", { replace: true });
  }, [session, navigate]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      await signIn(email.trim(), password);
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-5 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-primary/15 text-primary">
            <Cpu className="h-4 w-4" />
          </div>
          <div>
            <h1 className="text-base font-bold leading-none tracking-tight">RydeResolve</h1>
            <p className="mt-1 text-[11px] leading-none text-muted-foreground">
              Human Reviewer Portal
            </p>
          </div>
        </div>

        <form
          onSubmit={submit}
          className="rounded-xl border border-border bg-card/60 px-5 py-5 shadow-sm"
        >
          <h2 className="flex items-center gap-1.5 text-sm font-semibold tracking-tight">
            <ShieldCheck className="h-4 w-4 text-primary" />
            Sign in to the dispute board
          </h2>
          <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
            Operations reviewers triage the SLA queue, confirm agent determinations and close
            the learning loop on escalations.
          </p>

          <div className="mt-5 grid gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="email" className="text-[10px] uppercase tracking-wide">
                Work email
              </Label>
              <Input
                id="email"
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="h-9 text-sm"
                required
              />
            </div>

            <div className="grid gap-1.5">
              <Label htmlFor="password" className="text-[10px] uppercase tracking-wide">
                Password
              </Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="h-9 text-sm"
                required
              />
            </div>

            {(error || authError) && (
              <p className="flex items-start gap-1.5 whitespace-normal break-words text-xs leading-relaxed text-red-300">
                <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                {error ?? authError}
              </p>
            )}

            <Button type="submit" disabled={authPending} className="mt-1 h-9 w-full gap-1.5">
              {authPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <ArrowRight className="h-3.5 w-3.5" />
              )}
              {authPending ? "Authenticating…" : "Sign in"}
            </Button>
          </div>
        </form>

        <p className="mt-3 rounded-lg border border-dashed border-border px-3 py-2 text-center text-[11px] leading-relaxed text-muted-foreground">
          Demo credentials · <span className="font-mono">reviewer@ryde.com</span> /{" "}
          <span className="font-mono">admin2026</span>
        </p>

      </div>
    </div>
  );
}
