import type { Metadata } from "next";
import type { ReactNode } from "react";

// The sign-in screen was showing up in `site:getbeam.fyi` results and wasting
// crawl budget on a non-content page. The page itself is a client component
// (Clerk <SignIn>), so noindex has to live on a server layout. Kept crawlable
// (follow) so the directive is seen and outbound links still pass.
export const metadata: Metadata = {
  robots: { index: false, follow: true },
};

export default function SignInLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
