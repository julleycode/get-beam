"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// Legacy email/password login is retired. Clerk (/sign-in) is the live auth route.
// This page now redirects so any remaining links to /login don't dead-end users.
export default function LoginPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/sign-in");
  }, [router]);

  return (
    <div className="flex min-h-screen items-center justify-center">
      <p className="text-muted-foreground">Loading...</p>
    </div>
  );
}
