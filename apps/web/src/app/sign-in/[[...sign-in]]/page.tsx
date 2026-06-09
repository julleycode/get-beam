"use client";

import { SignIn } from "@clerk/nextjs";

export default function SignInPage() {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      {/* Land on the dashboard after sign-in — without this, Clerk defaults to
          "/", which re-enters the home redirect and bounces the user. */}
      <SignIn fallbackRedirectUrl="/dashboard" />
    </div>
  );
}
