/**
 * COMPLIANCE REQUIREMENT — do not delete, do not rename the testid.
 *
 * graph-erasure-compliance C-24/C-25, AC-9: the cross-tenant disclosure must
 * be visible BEFORE or DURING the pixel-install step. It is therefore rendered
 * outside any `detecting` branch and shows in both states.
 *
 * There is a live e2e assertion on BOTH the `data-testid` and the literal
 * string "cross-tenant identity"
 * (apps/web/e2e/onboarding.spec.ts — "AC-9: cross-tenant disclosure is visible
 * on the pixel-install step"). Losing either breaks the gate.
 *
 * Shared by the conversational flow and the classic add-site form so the two
 * install surfaces cannot drift apart.
 *
 * REQUIREMENTS PLACEHOLDER, NOT COUNSEL-APPROVED WORDING.
 */
export function CrossTenantDisclosure({ className }: { className?: string }) {
  return (
    <div
      data-testid="cross-tenant-disclosure"
      className={
        className ??
        "mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-200"
      }
    >
      <p className="font-medium">
        Heads up: identifications are shared across Beam customers
      </p>
      <p className="mt-1">
        Beam runs a shared cross-tenant identity network. A visitor identified
        on your site may also be identified on other Beam customers&apos; sites,
        and vice versa. The pooled fields are email, name,
        city/region/country, and the browser fingerprint — never your
        page-level event data. See the{" "}
        <a
          href="/beam/privacy.html"
          className="underline underline-offset-2"
          target="_blank"
          rel="noreferrer"
        >
          privacy policy
        </a>{" "}
        for what is pooled and how a person requests erasure.
      </p>
    </div>
  );
}
