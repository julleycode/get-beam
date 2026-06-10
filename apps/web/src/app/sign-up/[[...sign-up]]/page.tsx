"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { SignUp } from "@clerk/nextjs";
import { api } from "@/lib/api";

function Loading() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <p className="text-muted-foreground">Loading...</p>
    </div>
  );
}

/**
 * Private-beta signup. Only reachable with a valid invite token (from the
 * "you're in" email → /signup?invite=<token> → here). The token is validated
 * server-side; anything missing/invalid is bounced to the waitlist, so signup
 * stays closed to the public.
 */
function InviteGatedSignUp() {
  const router = useRouter();
  const params = useSearchParams();
  const [state, setState] = useState<"checking" | "ok" | "denied">("checking");
  const [email, setEmail] = useState<string | undefined>(undefined);

  useEffect(() => {
    // Resolve the invite token, preferring the URL but falling back to one
    // stashed on first load. Clerk's signup is multi-step and navigates within
    // /sign-up/* (e.g. email verification), dropping the ?invite query param —
    // without this fallback the guard would yank the user out mid-signup and the
    // account would never be created.
    let token = params.get("invite");
    try {
      if (token) sessionStorage.setItem("beam_invite", token);
      else token = sessionStorage.getItem("beam_invite");
    } catch {
      /* sessionStorage blocked — fall back to the URL token only */
    }

    if (!token) {
      setState("denied");
      return;
    }
    let cancelled = false;
    api
      .validateInvite(token)
      .then((res) => {
        if (cancelled) return;
        if (res.valid) {
          setEmail(res.email ?? undefined);
          setState("ok");
        } else {
          setState("denied");
        }
      })
      .catch(() => {
        if (!cancelled) setState("denied");
      });
    return () => {
      cancelled = true;
    };
  }, [params]);

  useEffect(() => {
    if (state === "denied") router.replace("/beam/index.html");
  }, [state, router]);

  if (state !== "ok") return <Loading />;

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <SignUp
        path="/sign-up"
        routing="path"
        signInUrl="/sign-in"
        fallbackRedirectUrl="/dashboard"
        initialValues={email ? { emailAddress: email } : undefined}
      />
    </div>
  );
}

// Rendering <SignUp> without a ClerkProvider (publishable key missing) throws
// at render and white-screens signup — same failure mode as the past
// NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY outage. Guard like layout.tsx.
const HAS_CLERK = !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

export default function SignUpPage() {
  if (!HAS_CLERK) {
    return (
      <div className="flex min-h-screen items-center justify-center p-4">
        <p className="text-muted-foreground text-sm text-center max-w-sm">
          Sign-up is temporarily unavailable (authentication is not
          configured). Please try again shortly or contact hello@getbeam.fyi.
        </p>
      </div>
    );
  }
  return (
    <Suspense fallback={<Loading />}>
      <InviteGatedSignUp />
    </Suspense>
  );
}
