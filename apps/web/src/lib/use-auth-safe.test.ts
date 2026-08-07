import { describe, expect, it, vi } from "vitest";

import type { useAuthSafe as UseAuthSafe } from "@/lib/use-auth-safe";

// use-auth-safe picks its implementation at module-load time from
// NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY, so the env has to be cleared before the
// import happens — a static top-level import would evaluate the module first
// and lock in whatever the ambient env said. Hence resetModules + dynamic
// import per load. The legacy implementation calls no React hooks, so it is
// safe to invoke outside a component in this node-environment suite.
async function loadLegacyAuthSafe(): Promise<typeof UseAuthSafe> {
  vi.stubEnv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "");
  vi.resetModules();
  return (await import("@/lib/use-auth-safe")).useAuthSafe;
}

describe("useAuthSafe without Clerk", () => {
  it("hands back the same auth object on every call", async () => {
    const useAuthSafe = await loadLegacyAuthSafe();

    expect(useAuthSafe()).toBe(useAuthSafe());
  });

  it("keeps getToken and signOut referentially stable", async () => {
    // The regression this locks down: when these were rebuilt per call, every
    // render produced a new getToken identity. Consumers list it in useEffect
    // dependency arrays, so the effect re-ran each render, re-fetched, stored a
    // fresh object via setState, and re-rendered — an unbounded fetch loop
    // (~30 req/s) against the live API on the billing page and API keys card.
    const useAuthSafe = await loadLegacyAuthSafe();

    expect(useAuthSafe().getToken).toBe(useAuthSafe().getToken);
    expect(useAuthSafe().signOut).toBe(useAuthSafe().signOut);
  });

  it("still reports a signed-in session with no token", async () => {
    const useAuthSafe = await loadLegacyAuthSafe();
    const auth = useAuthSafe();

    expect(auth.isLoaded).toBe(true);
    expect(auth.isSignedIn).toBe(true);
    await expect(auth.getToken()).resolves.toBeNull();
  });
});
