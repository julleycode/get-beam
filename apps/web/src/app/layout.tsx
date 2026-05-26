import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import { cn } from "@/lib/utils";
import { ClerkTokenSync } from "@/components/clerk-token-sync";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: "ReTargetAgent",
  description: "AI-powered retargeting for your website",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <ClerkProvider>
      <html lang="en" className="dark">
        <body className={cn(inter.variable, "font-sans antialiased")}>
          <ClerkTokenSync />
          {children}
        </body>
      </html>
    </ClerkProvider>
  );
}
