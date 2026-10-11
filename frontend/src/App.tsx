import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route } from 'react-router-dom';
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AnimatedRoutes } from "@/components/AnimatedRoutes";
import { PageTransition } from "@/components/PageTransition";
import { CasePersistenceProvider, useCaseStore } from "@/components/CasePersistenceContext";
import Index from "./pages/Index";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import NotFound from "./pages/NotFound";

/**
 * Configure TanStack Query client with optimized defaults
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Data considered fresh for 1 minute
      staleTime: 60 * 1000,
      // Cache data for 5 minutes
      gcTime: 5 * 60 * 1000,
      // Retry failed requests once
      retry: 1,
      // Don't refetch on window focus by default
      refetchOnWindowFocus: false,
      // Don't refetch on reconnect by default
      refetchOnReconnect: false,
    },
    mutations: {
      // Retry failed mutations once
      retry: 1,
    },
  },
});

function HomeGate() {
  const { session } = useCaseStore();
  return <Navigate to={session ? "/dashboard" : "/login"} replace />;
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <Toaster />
        <BrowserRouter>
          {/* Phase 3.2: arbitration cache + reviewer session live above the
              router so /login, /dashboard and /review all share one store. */}
          <CasePersistenceProvider>
            <AnimatedRoutes>
              <Route
                path="/"
                data-genie-title="Home"
                data-genie-key="Home"
                element={<PageTransition transition="fade"><HomeGate /></PageTransition>}
              />
              <Route
                path="/login"
                data-genie-key="Login"
                data-genie-title="Reviewer Sign In"
                element={<PageTransition transition="fade"><Login /></PageTransition>}
              />
              <Route
                path="/dashboard"
                data-genie-key="Dashboard"
                data-genie-title="Reviewer Dashboard"
                element={<PageTransition transition="slide-up"><Dashboard /></PageTransition>}
              />
              <Route
                path="/review"
                data-genie-title="Case Review"
                data-genie-key="Review"
                element={<PageTransition transition="slide-up"><Index /></PageTransition>}
              />
              {/* ADD ALL CUSTOM ROUTES ABOVE THE CATCH-ALL "*" ROUTE */}
              <Route path="*" data-genie-key="NotFound" data-genie-title="Not Found" element={<PageTransition transition="fade"><NotFound /></PageTransition>} />
            </AnimatedRoutes>
          </CasePersistenceProvider>
        </BrowserRouter>
      </TooltipProvider>
    </QueryClientProvider>
  );
}

export default App
