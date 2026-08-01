"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { SignIn } from "@clerk/nextjs";

// Rendering <SignIn> without a ClerkProvider (publishable key missing) throws
// at render. Without Clerk, local JWT auth lives at /login — redirect there.
const HAS_CLERK = !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

export default function SignInPage() {
  const router = useRouter();

  useEffect(() => {
    if (!HAS_CLERK) {
      router.replace("/login");
    }
  }, [router]);

  if (!HAS_CLERK) {
    return (
      <div className="flex min-h-screen items-center justify-center p-4">
        <p className="text-muted-foreground text-sm text-center max-w-sm">
          Redirecting to local login…
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
