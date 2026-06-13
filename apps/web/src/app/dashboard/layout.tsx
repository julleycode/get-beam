"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { api } from "@/lib/api";
import { BeamLogo } from "@/components/beam-logo";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

const HAS_CLERK = !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

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

// adminOnly items are hidden until /auth/me confirms is_admin (no flash for
// non-admins while loading — the backend rejects non-admins on those pages).
const BOTTOM_ITEMS: { href: string; label: string; adminOnly?: boolean }[] = [
  { href: "/dashboard/blog", label: "Blog", adminOnly: true },
  { href: "/dashboard/feature-board", label: "Feature Board" },
  { href: "/dashboard/billing", label: "Billing" },
  { href: "/dashboard/waitlist", label: "Waitlist", adminOnly: true },
  { href: "/dashboard/feature-requests", label: "Feature Requests", adminOnly: true },
  { href: "/dashboard/settings", label: "Settings" },
];

// Set by the sign-up page so the invite token survives Clerk's multi-step
// signup flow (see sign-up/[[...sign-up]]/page.tsx).
const INVITE_TOKEN_KEY = "beam_invite";

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
      className={`rounded-full px-4 py-2 text-sm transition-all ${
        isActive
          ? "bg-[hsl(345,100%,60%)] text-[#FAF6F0] font-medium shadow-[0_1px_0_rgba(43,37,48,0.1),0_4px_12px_-4px_rgba(255,51,102,0.35)]"
          : "text-muted-foreground hover:text-foreground hover:bg-secondary"
      }`}
    >
      {label}
    </Link>
  );
}

/**
 * Clerk-aware sign-out button. Only rendered when Clerk is configured.
 * Isolated in its own component so useAuth() is always called (no conditional hooks).
 */
function ClerkSignOutButton() {
  const { signOut } = useAuth();
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => {
        api.clearToken();
        signOut({ redirectUrl: "/sign-in" });
      }}
    >
      Sign out
    </Button>
  );
}

/** Fallback sign-out button when Clerk is not configured. */
function LegacySignOutButton() {
  const router = useRouter();
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => {
        api.clearToken();
        router.replace("/login");
      }}
    >
      Sign out
    </Button>
  );
}

/**
 * Clerk auth guard — redirects if not signed in.
 * Only rendered when Clerk is configured.
 */
function ClerkAuthGuard() {
  const { isLoaded, isSignedIn } = useAuth();
  const router = useRouter();
  const consumeAttempted = useRef(false);

  useEffect(() => {
    // Only redirect once Clerk has fully resolved the session. Acting on a
    // transient `isSignedIn === false` while Clerk is still hydrating (common
    // with slow/rate-limited dev instances) bounces signed-in users to
    // /sign-in, which then redirects them back out — the dashboard↔sign-in loop.
    if (isLoaded && isSignedIn === false) {
      router.replace("/sign-in");
    }
  }, [isLoaded, isSignedIn, router]);

  useEffect(() => {
    // Mark the invite token used on the first signed-in dashboard visit so a
    // forwarded invite link can't mint unlimited accounts. One attempt per
    // mount; on terminal outcomes (consumed/invalid) the token is discarded,
    // on transient failures it stays for a later visit.
    if (!isLoaded || !isSignedIn || consumeAttempted.current) return;
    let inviteToken: string | null = null;
    try {
      inviteToken = sessionStorage.getItem(INVITE_TOKEN_KEY);
    } catch {
      return; // sessionStorage blocked — nothing to consume
    }
    if (!inviteToken) return;
    if (!api.getToken()) return; // API token not synced yet; retry next mount
    consumeAttempted.current = true;
    api
      .consumeInvite(inviteToken)
      .then(() => {
        try {
          sessionStorage.removeItem(INVITE_TOKEN_KEY);
        } catch {
          /* ignore */
        }
      })
      .catch((err) => {
        console.warn("consume-invite failed (will retry next visit)", err);
      });
  }, [isLoaded, isSignedIn]);

  return null;
}

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [userEmail, setUserEmail] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    const token = api.getToken();
    // Without Clerk, require a legacy token
    if (!HAS_CLERK && !token) {
      router.replace("/login");
      return;
    }
    api
      .getMe()
      .then((u) => {
        setUserEmail(u.email);
        setIsAdmin(u.is_admin === true);
      })
      .catch(() => {
        if (!HAS_CLERK) {
          api.clearToken();
          router.replace("/login");
        }
      });
  }, [router]);

  return (
    <div className="flex min-h-screen">
      {/* Clerk auth guard (only when Clerk is active) */}
      {HAS_CLERK && <ClerkAuthGuard />}

      <aside className="w-56 border-r border-[rgba(43,37,48,0.08)] bg-card p-4 flex flex-col">
        <div className="mb-6">
          <h1 className="text-xl font-serif font-semibold tracking-tight flex items-center gap-2">
            <BeamLogo />
            Beam
          </h1>
          <p className="text-xs text-muted-foreground truncate mt-1">{userEmail}</p>
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

          {BOTTOM_ITEMS.filter((item) => !item.adminOnly || isAdmin).map(
            (item) => (
              <NavLink
                key={item.href}
                href={item.href}
                label={item.label}
                pathname={pathname}
              />
            )
          )}
        </nav>
        <Separator className="my-2" />
        {HAS_CLERK ? <ClerkSignOutButton /> : <LegacySignOutButton />}
      </aside>
      <main className="flex-1 p-6 overflow-auto">{children}</main>
    </div>
  );
}
