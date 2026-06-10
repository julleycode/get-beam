"use client";

import { SignIn } from "@clerk/nextjs";

// Rendering <SignIn> without a ClerkProvider (publishable key missing) throws
// at render and white-screens the entire auth entry — the exact failure mode
// of the past NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY outage. Guard like layout.tsx.
const HAS_CLERK = !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

export default function SignInPage() {
  if (!HAS_CLERK) {
    return (
      <div className="flex min-h-screen items-center justify-center p-4">
        <p className="text-muted-foreground text-sm text-center max-w-sm">
          Sign-in is temporarily unavailable (authentication is not
          configured). Please try again shortly or contact hello@getbeam.fyi.
        </p>
      </div>
    );
  }
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      {/* Land on the dashboard after sign-in — without this, Clerk defaults to
          "/", which re-enters the home redirect and bounces the user. */}
      <SignIn fallbackRedirectUrl="/dashboard" />
    </div>
  );
}
