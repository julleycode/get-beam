import { cn } from "@/lib/utils";

// Shared LinkedIn Terms-of-Service warning. Extracted verbatim from the
// Connected Accounts card so the onboarding wizard's connect step shows the
// IDENTICAL wording rather than a re-typed near-duplicate (onboarding AC8).
// Rendered output at the original call site is unchanged.
export function LinkedInTosWarning({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "rounded-md border border-warning/30 bg-warning/10 p-3 text-sm text-warning",
        className
      )}
    >
      <strong>Warning:</strong> automating LinkedIn is against LinkedIn&apos;s
      Terms of Service and can get your account restricted or banned. Use a low
      daily volume and only with accounts you&apos;re willing to risk.
    </div>
  );
}
