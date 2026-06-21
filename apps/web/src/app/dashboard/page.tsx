import { auth } from "@clerk/nextjs/server";
import {
  QueryClient,
  dehydrate,
  HydrationBoundary,
} from "@tanstack/react-query";
import OverviewClient from "./overview-client";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function serverGet(path: string, token: string): Promise<unknown> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

/**
 * Server-prefetch the Overview's data (sites + per-site stats + the user) so the
 * HTML ships WITH it. This removes the client's wait on Clerk's 320KB JS + token
 * round-trip before the page can paint — the slowest part for far-from-origin
 * users. Best-effort: any failure (no server token, fetch error) falls through
 * to the client fetching it itself (OverviewClient + the api client's 401-retry).
 */
export default async function DashboardPage() {
  const qc = new QueryClient();

  try {
    const { getToken } = auth();
    const token = await getToken();
    if (token) {
      await Promise.all([
        qc.prefetchQuery({
          queryKey: ["dashboard-overview"],
          queryFn: () => serverGet("/api/v1/dashboard/overview", token),
        }),
        qc.prefetchQuery({
          queryKey: ["me"],
          queryFn: () => serverGet("/api/v1/auth/me", token),
        }),
      ]);
    }
  } catch {
    // Server prefetch unavailable — the client will fetch on mount.
  }

  return (
    <HydrationBoundary state={dehydrate(qc)}>
      <OverviewClient />
    </HydrationBoundary>
  );
}
