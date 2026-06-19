"use client";

import { SignUp } from "@clerk/nextjs";

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
    <div className="flex min-h-screen items-center justify-center p-4">
      <SignUp
        path="/sign-up"
        routing="path"
        signInUrl="/sign-in"
        fallbackRedirectUrl="/dashboard"
      />
    </div>
  );
}
