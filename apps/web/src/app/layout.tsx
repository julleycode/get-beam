import type { Metadata } from "next";
import { Inter, Fraunces } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import { Analytics } from "@vercel/analytics/next";
import { cn } from "@/lib/utils";
import { ClerkTokenSync } from "@/components/clerk-token-sync";
import { Providers } from "./providers";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });
const fraunces = Fraunces({ subsets: ["latin"], variable: "--font-serif", weight: ["400", "500", "600"] });

const HAS_CLERK = !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

export const metadata: Metadata = {
  title: "Beam",
  description: "See who visits your site. Reach out on their turf.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const inner = (
    <html lang="en">
      <body className={cn(inter.variable, fraunces.variable, "font-sans antialiased")}>
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
