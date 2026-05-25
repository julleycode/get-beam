"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Overview" },
  { href: "/dashboard/visitors", label: "Visitors" },
  { href: "/dashboard/segments", label: "Segments" },
  { href: "/dashboard/campaigns", label: "Campaigns" },
  { href: "/dashboard/exports", label: "Exports" },
  { href: "/dashboard/settings", label: "Settings" },
];

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [userEmail, setUserEmail] = useState("");

  useEffect(() => {
    const token = api.getToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    api.getMe().then((u) => setUserEmail(u.email)).catch(() => {
      api.clearToken();
      router.replace("/login");
    });
  }, [router]);

  function handleLogout() {
    api.clearToken();
    router.replace("/login");
  }

  return (
    <div className="flex min-h-screen">
      <aside className="w-56 border-r bg-card p-4 flex flex-col">
        <div className="mb-6">
          <h1 className="text-lg font-bold">ReTargetAgent</h1>
          <p className="text-xs text-muted-foreground truncate">{userEmail}</p>
        </div>
        <nav className="flex flex-col gap-1 flex-1">
          {NAV_ITEMS.map((item) => {
            const isActive =
              pathname === item.href ||
              (item.href !== "/dashboard" && pathname.startsWith(item.href));
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`rounded-md px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? "bg-accent text-accent-foreground font-medium"
                    : "text-muted-foreground hover:bg-accent/50"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <Separator className="my-2" />
        <Button variant="ghost" size="sm" onClick={handleLogout}>
          Sign out
        </Button>
      </aside>
      <main className="flex-1 p-6 overflow-auto">{children}</main>
    </div>
  );
}
