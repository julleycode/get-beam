"use client";

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { SignUp } = require("@clerk/nextjs");

export default function SignUpPage() {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <SignUp />
    </div>
  );
}
