import type { Metadata } from "next";
import { Inter, Fraunces, DM_Mono } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import { Analytics } from "@vercel/analytics/next";
import { cn } from "@/lib/utils";
import { ClerkTokenSync } from "@/components/clerk-token-sync";
import { Providers } from "./providers";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });
const fraunces = Fraunces({ subsets: ["latin"], variable: "--font-serif", weight: ["400", "500", "600"] });
const dmMono = DM_Mono({ subsets: ["latin"], variable: "--font-mono", weight: ["400", "500"] });

const HAS_CLERK = !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

export const metadata: Metadata = {
  title: "Beam",
  description: "See who visits your site. Reach out on their turf.",
};

// Warm DNS/TLS to the external Clerk + API origins during HTML parse, so the
// 320KB Clerk script and the first /auth/me + /sites fetches don't each pay a
// fresh handshake on cold dashboard loads. Hosts come from env (correct in dev
// and prod): Clerk's frontend-API host is base64-encoded in the publishable key.
const CLERK_HOST = (() => {
  const pk = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY || "";
  try {
    return Buffer.from(pk.split("_")[2] || "", "base64").toString("utf8").replace(/\$$/, "") || null;
  } catch {
    return null;
  }
})();
const API_ORIGIN = (() => {
  try {
    return new URL(process.env.NEXT_PUBLIC_API_URL || "").origin;
  } catch {
    return null;
  }
})();

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const inner = (
    <html lang="en">
      <head>
        {CLERK_HOST && <link rel="preconnect" href={`https://${CLERK_HOST}`} crossOrigin="anonymous" />}
        {API_ORIGIN && <link rel="preconnect" href={API_ORIGIN} crossOrigin="anonymous" />}
      </head>
      <body className={cn(inter.variable, fraunces.variable, dmMono.variable, "font-sans antialiased")}>
        {HAS_CLERK && <ClerkTokenSync />}
        <Providers>{children}</Providers>
        <Analytics />
      </body>
    </html>
  );

  if (HAS_CLERK) {
    return (
      <ClerkProvider signInUrl="/sign-in" signUpUrl="/sign-up">
        {inner}
      </ClerkProvider>
    );
  }

  return inner;
}
