import { redirect } from "next/navigation";

/**
 * Private beta. An invite link (?invite=<token>) forwards to the Clerk signup
 * route with the token preserved; everything else is bounced to the waitlist.
 */
export default function SignupPage({
  searchParams,
}: {
  searchParams: { invite?: string };
}) {
  const invite = searchParams?.invite;
  if (invite) {
    redirect(`/sign-up?invite=${encodeURIComponent(invite)}`);
  }
  redirect("/beam/index.html");
}
