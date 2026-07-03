import { useQuery } from "@tanstack/react-query";
import { api, type BillingStatus } from "@/lib/api";

// Shared billing/usage fetch. Keyed ["billing"] so the sidebar badge, usage
// warning banner, and upgrade modal reuse ONE request (react-query dedupes)
// instead of each firing its own. Mirrors the ["me"] query in the dashboard
// layout: cached briefly, fails quiet (surfaces null so callers can hide).
export function useBillingStatus() {
  return useQuery<BillingStatus>({
    queryKey: ["billing"],
    queryFn: () => api.getBillingStatus(),
    staleTime: 60_000,
    retry: false,
  });
}
