"use client";

import { useEffect, useState } from "react";
import { SignUp } from "@clerk/nextjs";
import { Gift } from "lucide-react";
import { api } from "@/lib/api";

// Rendering <SignUp> without a ClerkProvider (publishable key missing) throws
// at render and white-screens signup — same failure mode as the past
// NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY outage. Guard like layout.tsx.
const HAS_CLERK = !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

// Read by dashboard/layout.tsx after first sign-in to claim the referral.
// localStorage (not sessionStorage): Clerk's OAuth redirect can land in a
// fresh browsing context, which would lose a sessionStorage value.
const REFERRAL_CODE_KEY = "beam_ref";

// Waitlist invite token (?invite=...), consumed by dashboard/layout.tsx after
// first sign-in so a forwarded invite link can't mint unlimited accounts.
// Same localStorage rationale as the referral code.
const INVITE_TOKEN_KEY = "beam_invite";

export default function SignUpPage() {
  const [referrerName, setReferrerName] = useState<string | null>(null);

  useEffect(() => {
    // window.location instead of useSearchParams: no Suspense boundary needed
    // at build time, and this only has to run client-side anyway.
    let code: string | null = null;
    try {
      const params = new URLSearchParams(window.location.search);
      const invite = params.get("invite");
      if (invite) localStorage.setItem(INVITE_TOKEN_KEY, invite);
      code = params.get("ref");
      if (code) localStorage.setItem(REFERRAL_CODE_KEY, code);
      else code = localStorage.getItem(REFERRAL_CODE_KEY);
    } catch {
      return; // storage blocked — signup still works, just no referral credit
    }
    if (!code) return;
    api
      .validateReferral(code)
      .then((res) => {
        if (res.valid) setReferrerName(res.referrer_name || "A Beam user");
      })
      .catch(() => {
        // validation is cosmetic (banner only); the claim after sign-in is
        // what actually counts, so a failed check here is not an error state
      });
  }, []);

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
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-4">
      {referrerName ? (
        <div className="flex max-w-sm items-center gap-2.5 rounded-lg border border-border bg-secondary px-4 py-3 text-sm">
          <Gift className="h-4 w-4 shrink-0 text-primary" />
          <span>
            <strong>{referrerName}</strong> invited you. You both get +10
            identified visitors/month once your pixel goes live.
          </span>
        </div>
      ) : null}
      <SignUp
        path="/sign-up"
        routing="path"
        signInUrl="/sign-in"
        fallbackRedirectUrl="/dashboard"
      />
    </div>
  );
}
