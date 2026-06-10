"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { api } from "@/lib/api";
import { BrandSplash } from "@/components/skeletons";

const HAS_CLERK = !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

function Loading() {
  return <BrandSplash />;
}

/**
 * Clerk-aware landing redirect. Isolated in its own component so useAuth() only
 * runs inside ClerkProvider (no conditional hooks). Routes by the Clerk session
 * — NOT the legacy localStorage token, which a Clerk user never has and which
 * caused the /sign-in bounce loop.
 */
function ClerkHome() {
  const router = useRouter();
  const { isLoaded, isSignedIn } = useAuth();

  useEffect(() => {
    // Wait for Clerk to finish hydrating before deciding. Acting on a transient
    // isSignedIn === false (common with a dev Clerk instance) bounces a
    // signed-in user back to /sign-in → / → /sign-in forever.
    if (!isLoaded) return;
    router.replace(isSignedIn ? "/dashboard" : "/sign-in");
  }, [router, isLoaded, isSignedIn]);

  return <Loading />;
}

/** Legacy (no-Clerk / local dev) redirect using the localStorage token. */
function LegacyHome() {
  const router = useRouter();

  useEffect(() => {
    router.replace(api.getToken() ? "/dashboard" : "/login");
  }, [router]);

  return <Loading />;
}

export default function Home() {
  return HAS_CLERK ? <ClerkHome /> : <LegacyHome />;
}
