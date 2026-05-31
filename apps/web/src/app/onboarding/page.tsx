import { redirect } from "next/navigation";

/**
 * /onboarding → redirects to the static Beam onboarding experience.
 *
 * The CTA buttons on the landing page (public/beam/index.html) link to
 * /onboarding. The actual onboarding chat lives at /beam/onboarding.html
 * (a static HTML file in public/).
 */
export default function OnboardingRedirect() {
  redirect("/beam/onboarding.html");
}
