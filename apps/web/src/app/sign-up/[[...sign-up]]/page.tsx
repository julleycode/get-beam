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
  const invite = params.get("invite");
  const [state, setState] = useState<"checking" | "ok" | "denied">("checking");
  const [email, setEmail] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (!invite) {
      setState("denied");
      return;
    }
    let cancelled = false;
    api
      .validateInvite(invite)
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
  }, [invite]);

  useEffect(() => {
    if (state === "denied") router.replace("/beam/index.html");
  }, [state, router]);

  if (state !== "ok") return <Loading />;

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <SignUp
        signInUrl="/sign-in"
        fallbackRedirectUrl="/dashboard"
        initialValues={email ? { emailAddress: email } : undefined}
      />
    </div>
  );
}

export default function SignUpPage() {
  return (
    <Suspense fallback={<Loading />}>
      <InviteGatedSignUp />
    </Suspense>
  );
}
