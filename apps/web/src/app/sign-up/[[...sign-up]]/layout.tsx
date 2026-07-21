import type { Metadata } from "next";
import type { ReactNode } from "react";

// Same as sign-in: keep the auth screen out of the index. The page is a client
// component (Clerk <SignUp>), so noindex lives on this server layout.
export const metadata: Metadata = {
  robots: { index: false, follow: true },
};

export default function SignUpLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
