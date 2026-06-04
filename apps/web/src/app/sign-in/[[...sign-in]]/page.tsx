import { redirect } from "next/navigation";

/** Redirect /sign-in → /login (legacy auth page that works with or without Clerk) */
export default function SignInRedirect() {
  redirect("/login");
}
