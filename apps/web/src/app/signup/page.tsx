import { redirect } from "next/navigation";

/**
 * Public signup. Forwards to the Clerk signup route, preserving any query
 * params (e.g. ?plan=pro&interval=monthly from the pricing page) so the
 * post-signup checkout still has them.
 */
export default function SignupPage({
  searchParams,
}: {
  searchParams: Record<string, string | string[] | undefined>;
}) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(searchParams)) {
    if (typeof v === "string") qs.set(k, v);
  }
  const s = qs.toString();
  redirect(s ? `/sign-up?${s}` : "/sign-up");
}
