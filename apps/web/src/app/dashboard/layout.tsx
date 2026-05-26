"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import Link from "next/link";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

const EASYTRACK_ITEMS = [
  { href: "/dashboard", label: "Overview" },
  { href: "/dashboard/visitors", label: "Visitors" },
  { href: "/dashboard/segments", label: "Segments" },
  { href: "/dashboard/campaigns", label: "Campaigns" },
  { href: "/dashboard/exports", label: "Exports" },
];

const EASYENGAGE_ITEMS = [
  { href: "/dashboard/feed", label: "Feed" },
  { href: "/dashboard/drafts", label: "Drafts" },
  { href: "/dashboard/social-accounts", label: "Social Accounts" },
];

const BOTTOM_ITEMS = [
  { href: "/dashboard/settings", label: "Settings" },
];

function NavLink({
  href,
  label,
  pathname,
}: {
  href: string;
  label: string;
  pathname: string;
}) {
  const isActive =
    pathname === href ||
    (href !== "/dashboard" && pathname.startsWith(href));
  return (
    <Link
      href={href}
      className={`rounded-md px-3 py-2 text-sm transition-colors ${
        isActive
          ? "bg-accent text-accent-foreground font-medium"
          : "text-muted-foreground hover:bg-accent/50"
      }`}
    >
      {label}
    </Link>
  );
}

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const { signOut, isSignedIn } = useAuth();
  const [userEmail, setUserEmail] = useState("");

  useEffect(() => {
    const token = api.getToken();
    if (!token && !isSignedIn) {
      router.replace("/login");
      return;
    }
    api
      .getMe()
      .then((u) => setUserEmail(u.email))
      .catch(() => {
        if (!isSignedIn) {
          api.clearToken();
          router.replace("/login");
        }
      });
  }, [router, isSignedIn]);

  function handleLogout() {
    api.clearToken();
    if (isSignedIn) {
      signOut({ redirectUrl: "/login" });
    } else {
      router.replace("/login");
    }
  }

  return (
    <div className="flex min-h-screen">
      <aside className="w-56 border-r bg-card p-4 flex flex-col">
        <div className="mb-6">
          <h1 className="text-lg font-bold">ReTargetAgent</h1>
          <p className="text-xs text-muted-foreground truncate">{userEmail}</p>
        </div>
        <nav className="flex flex-col gap-1 flex-1">
          <p className="px-3 py-1 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            EasyTrack
          </p>
          {EASYTRACK_ITEMS.map((item) => (
            <NavLink key={item.href} {...item} pathname={pathname} />
          ))}

          <Separator className="my-2" />

          <p className="px-3 py-1 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            EasyEngage
          </p>
          {EASYENGAGE_ITEMS.map((item) => (
            <NavLink key={item.href} {...item} pathname={pathname} />
          ))}

          <div className="flex-1" />

          {BOTTOM_ITEMS.map((item) => (
            <NavLink key={item.href} {...item} pathname={pathname} />
          ))}
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
