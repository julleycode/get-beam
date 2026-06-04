"use client";

import { useEffect, useState } from "react";

/**
 * /sign-in — Clerk SignIn page.
 *
 * Dynamically imports @clerk/nextjs SignIn to avoid SSR crash.
 * Falls back to redirect to /login (legacy) if Clerk isn't loaded.
 */
export default function SignInPage() {
  const [ClerkSignIn, setClerkSignIn] = useState<React.ComponentType | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    import("@clerk/nextjs")
      .then((mod) => {
        if (mod.SignIn) {
          setClerkSignIn(() => mod.SignIn);
        } else {
          setError(true);
        }
      })
      .catch(() => setError(true));
  }, []);

  if (error) {
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    return null;
  }

  if (!ClerkSignIn) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="animate-pulse text-muted-foreground">loading...</div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <ClerkSignIn
        appearance={{
          elements: {
            rootBox: "w-full max-w-md",
          },
        }}
      />
    </div>
  );
}
