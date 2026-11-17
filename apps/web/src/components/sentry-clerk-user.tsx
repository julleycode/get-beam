"use client";

import { useAuth } from "@clerk/nextjs";
import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

/**
 * Puts the Clerk user id on the browser Sentry scope. Never email or name.
 * Only mount this under ClerkProvider (see layout.tsx HAS_CLERK).
 */
export function SentryClerkUser() {
  const { isLoaded, userId } = useAuth();

  useEffect(() => {
    if (!isLoaded) return;
    if (userId) Sentry.setUser({ id: userId });
    else Sentry.setUser(null);
  }, [isLoaded, userId]);

  return null;
}
