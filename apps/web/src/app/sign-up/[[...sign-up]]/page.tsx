"use client";

import { useEffect, useState } from "react";

/**
 * /sign-up — Clerk SignUp page.
 *
 * Dynamically imports @clerk/nextjs SignUp to avoid SSR crash.
 * Falls back to redirect to /signup (legacy) if Clerk isn't loaded.
 */
export default function SignUpPage() {
  const [ClerkSignUp, setClerkSignUp] = useState<React.ComponentType | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    import("@clerk/nextjs")
      .then((mod) => {
        if (mod.SignUp) {
          setClerkSignUp(() => mod.SignUp);
        } else {
          setError(true);
        }
      })
      .catch(() => setError(true));
  }, []);

  if (error) {
    // Clerk not available — redirect to legacy signup
    if (typeof window !== "undefined") {
      window.location.href = "/signup";
    }
    return null;
  }

  if (!ClerkSignUp) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="animate-pulse text-muted-foreground">loading...</div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <ClerkSignUp
        appearance={{
          elements: {
            rootBox: "w-full max-w-md",
          },
        }}
      />
    </div>
  );
}
