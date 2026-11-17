import { auth } from "@clerk/nextjs/server";
import * as Sentry from "@sentry/nextjs";

/** Clerk user id on the Node request scope. Never throws, never sends email. */
export function bindServerClerkUser(): void {
  try {
    const { userId } = auth();
    if (userId) Sentry.setUser({ id: userId });
  } catch {
    // auth() outside a request (build) must not take the page down.
  }
}
