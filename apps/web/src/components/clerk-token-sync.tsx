"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect } from "react";
import { api } from "@/lib/api";

/**
 * Syncs Clerk's session token into the API client so all fetch calls
 * include the correct Authorization header. Renders nothing.
 */
export function ClerkTokenSync() {
  const { getToken, isSignedIn } = useAuth();

  useEffect(() => {
    if (!isSignedIn) {
      api.setClerkToken(null);
      api.setClerkTokenGetter(null);
      return;
    }

    // Let the API client fetch a FRESH token on demand to retry once on 401
    // (the cached token expires after ~60s; a slow form sits past that).
    api.setClerkTokenGetter(() => getToken());

    let cancelled = false;

    const syncToken = async () => {
      try {
        const token = await getToken();
        if (!cancelled) {
          api.setClerkToken(token);
        }
      } catch {
        // Token fetch failed — will retry on next render
      }
    };

    syncToken();

    // Refresh token periodically (Clerk tokens expire after ~60s)
    const interval = setInterval(syncToken, 50_000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [getToken, isSignedIn]);

  return null;
}
