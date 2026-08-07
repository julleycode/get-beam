"use client";

import { useAuth } from "@clerk/nextjs";

// Clerk's useAuth() throws when there is no <ClerkProvider> in the tree, which
// happens whenever NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY is unset (CI E2E builds and
// legacy-auth mode — see layout.tsx HAS_CLERK). The dashboard layout already
// guards its own useAuth calls behind HAS_CLERK-gated child components; use this
// hook in any *other* component that needs auth so it degrades gracefully off
// Clerk instead of crashing the page.
//
// HAS_CLERK is a build-time constant, so exactly one implementation is selected
// per build. Hook order stays stable across renders — no rules-of-hooks
// violation (the choice never flips at runtime).
const HAS_CLERK = !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

type SafeAuth = {
  isLoaded: boolean;
  isSignedIn: boolean;
  getToken: () => Promise<string | null>;
  signOut: () => Promise<void>;
};

// Legacy mode has no session to resolve, so this shape never varies. It is a
// module constant rather than a fresh object per call on purpose: callers put
// getToken in useEffect dependency arrays, and a new function identity on every
// render re-runs those effects every render. Paired with a setState that stores
// a fresh object/array (billing status, API key list), that loops forever and
// hammers the API. Clerk's own useAuth memoizes getToken with useCallback, so
// keeping this stable makes both auth paths behave the same.
const LEGACY_AUTH: SafeAuth = {
  isLoaded: true,
  isSignedIn: true,
  getToken: async () => null,
  signOut: async () => {},
};

function useLegacyAuth(): SafeAuth {
  return LEGACY_AUTH;
}

export const useAuthSafe: () => SafeAuth = HAS_CLERK
  ? (useAuth as unknown as () => SafeAuth)
  : useLegacyAuth;
