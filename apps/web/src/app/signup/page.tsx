import { redirect } from "next/navigation";

/** Private beta — sign-up blocked, redirect to landing page waitlist */
export default function SignupPage() {
  redirect("/beam/index.html");
}
