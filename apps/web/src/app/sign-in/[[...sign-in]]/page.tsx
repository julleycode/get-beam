"use client";

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { SignIn } = require("@clerk/nextjs");

export default function SignInPage() {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <SignIn />
    </div>
  );
}
