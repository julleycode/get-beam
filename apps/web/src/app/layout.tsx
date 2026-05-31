import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import { cn } from "@/lib/utils";
import { ClerkTokenSync } from "@/components/clerk-token-sync";
import { Providers } from "./providers";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: "Beam",
  description: "See who visits your site. Reach out on their turf.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const hasClerk = !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

  const content = (
    <html lang="en" className="dark">
      <body className={cn(inter.variable, "font-sans antialiased")}>
        {hasClerk && <ClerkTokenSync />}
        <Providers>{children}</Providers>
      </body>
    </html>
  );

  if (hasClerk) {
    return (
      <ClerkProvider signInUrl="/sign-in" signUpUrl="/sign-up">
        {content}
      </ClerkProvider>
    );
  }
  return content;
}
