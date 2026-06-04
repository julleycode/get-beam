import { redirect } from "next/navigation";

/** Redirect /sign-up → /signup (legacy auth page that works with or without Clerk) */
export default function SignUpRedirect() {
  redirect("/signup");
}
