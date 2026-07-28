"use client";

import { useCallback, useEffect, useRef, useState, type ComponentType } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { useQuery } from "@tanstack/react-query";
import {
  LayoutDashboard,
  Users,
  Layers,
  Megaphone,
  Plug,
  Rss,
  FileText,
  AtSign,
  Lightbulb,
  CreditCard,
  Shield,
  Menu,
  HelpCircle,
  Gift,
  Bot,
} from "lucide-react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { api } from "@/lib/api";
import { useBillingStatus } from "@/lib/use-billing";
import { planLabel } from "@/lib/plans";
import { cn } from "@/lib/utils";
import { BeamLogo } from "@/components/beam-logo";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { OnboardingTour } from "@/components/onboarding-tour";
import { ExpiringConnectionBanner } from "@/components/expiring-connection-banner";
import { TOUR_STEPS } from "@/lib/tour-steps";

const HAS_CLERK = !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

type NavItem = {
  href: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  adminOnly?: boolean;
  // Marks this link as an onboarding-tour target. The OnboardingTour spotlights
  // it via `aside [data-tour="<tour>"]`.
  tour?: string;
};

const EASYTRACK_ITEMS: NavItem[] = [
  { href: "/dashboard", label: "Overview", icon: LayoutDashboard, tour: "overview" },
  { href: "/dashboard/visitors", label: "Visitors", icon: Users, tour: "visitors" },
  { href: "/dashboard/agents", label: "Agents", icon: Bot, tour: "agents" },
  { href: "/dashboard/segments", label: "Segments", icon: Layers, tour: "segments" },
  { href: "/dashboard/campaigns", label: "Campaigns", icon: Megaphone, tour: "campaigns" },
  { href: "/dashboard/connectors", label: "Connectors", icon: Plug, tour: "connectors" },
];

const EASYENGAGE_ITEMS: NavItem[] = [
  { href: "/dashboard/feed", label: "Feed", icon: Rss, tour: "feed" },
  { href: "/dashboard/drafts", label: "Drafts", icon: FileText },
  { href: "/dashboard/social-accounts", label: "Social Accounts", icon: AtSign },
];

// Everyone (non-admin) bottom links.
const GENERAL_ITEMS: NavItem[] = [
  { href: "/dashboard/feature-board", label: "Feature Board", icon: Lightbulb },
  { href: "/dashboard/referrals", label: "Referrals", icon: Gift },
  { href: "/dashboard/billing", label: "Billing", icon: CreditCard },
];

// Single entry point to all admin tools (API Costs, Blog, Waitlist, Feature
// Requests). Only shown once /auth/me confirms is_admin; the hub page at
// /dashboard/admin links out to each tool.
const ADMIN_ITEM: NavItem = {
  href: "/dashboard/admin",
  label: "Admin",
  icon: Shield,
  adminOnly: true,
};

// Set by the sign-up page so the invite token survives Clerk's multi-step
// signup flow (see sign-up/[[...sign-up]]/page.tsx). localStorage — the
// Clerk OAuth redirect can land in a fresh context, losing sessionStorage.
const INVITE_TOKEN_KEY = "beam_invite";

// Referral code captured by the sign-up page (?ref=...). localStorage — the
// Clerk OAuth redirect can land in a fresh context, losing sessionStorage.
const REFERRAL_CODE_KEY = "beam_ref";

// Versioned so a future tour revision can re-trigger for everyone by bumping it.
const TOUR_DONE_KEY = "beam_tour_done_v1";

function NavLink({
  href,
  label,
  icon: Icon,
  pathname,
  onNavigate,
  tour,
}: {
  href: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  pathname: string;
  onNavigate?: () => void;
  tour?: string;
}) {
  const isActive =
    pathname === href ||
    (href !== "/dashboard" && pathname.startsWith(href));
  return (
    <Link
      href={href}
      onClick={onNavigate}
      data-tour={tour}
      className={cn(
        "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
        isActive
          ? "bg-primary font-medium text-primary-foreground shadow-sm"
          : "text-muted-foreground hover:bg-secondary hover:text-foreground"
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      {label}
    </Link>
  );
}

/**
 * Compact plan + usage badge in the sidebar. Always-visible awareness of the
 * current tier and how much of the monthly identify cap is spent — the primary
 * "there are paid tiers" signal. Clicks through to Billing. Fails quiet (hidden
 * while loading / on error), and shows "Unlimited" for the Max plan.
 */
function SidebarPlanBadge({ onNavigate }: { onNavigate?: () => void }) {
  const { data: billing } = useBillingStatus();
  if (!billing) return null;

  const { plan, monthly_identified_count: used, monthly_limit: limit } = billing;
  const pct =
    limit !== null && limit > 0
      ? Math.min(100, Math.round((used / limit) * 100))
      : 0;
  const near = pct >= 80;

  return (
    <Link
      href="/dashboard/billing"
      onClick={onNavigate}
      className="mb-1 block rounded-md border border-border bg-background/50 px-3 py-2 transition-colors hover:bg-secondary"
    >
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium text-foreground">{planLabel(plan)} plan</span>
        <span className={cn("tabular-nums", near ? "text-warning" : "text-muted-foreground")}>
          {limit === null ? "Unlimited" : `${used} / ${limit}`}
        </span>
      </div>
      {limit !== null && (
        <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-secondary">
          <div
            className={cn(
              "h-full rounded-full transition-all",
              pct >= 90 ? "bg-destructive" : near ? "bg-warning" : "bg-primary"
            )}
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
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
  const claimAttempted = useRef(false);

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
      inviteToken = localStorage.getItem(INVITE_TOKEN_KEY);
    } catch {
      return; // localStorage blocked — nothing to consume
    }
    if (!inviteToken) return;
    if (!api.getToken()) return; // API token not synced yet; retry next mount
    consumeAttempted.current = true;
    api
      .consumeInvite(inviteToken)
      .then(() => {
        // Resolves on both terminal outcomes ("consumed" and "invalid") —
        // either way the token is spent, so discard it. Transient failures
        // throw and land in .catch, keeping the token for a later visit.
        try {
          localStorage.removeItem(INVITE_TOKEN_KEY);
        } catch {
          /* ignore */
        }
      })
      .catch((err) => {
        console.warn("consume-invite failed (will retry next visit)", err);
      });
  }, [isLoaded, isSignedIn]);

  useEffect(() => {
    // Claim the referral captured at sign-up (?ref= → localStorage). Terminal
    // outcomes (claimed/invalid) discard the code; transient failures keep it
    // for a later visit. One attempt per mount, after the API token is synced.
    if (!isLoaded || !isSignedIn || claimAttempted.current) return;
    let refCode: string | null = null;
    try {
      refCode = localStorage.getItem(REFERRAL_CODE_KEY);
    } catch {
      return; // localStorage blocked — nothing to claim
    }
    if (!refCode) return;
    if (!api.getToken()) return; // API token not synced yet; retry next mount
    claimAttempted.current = true;
    api
      .claimReferral(refCode)
      .then(() => {
        try {
          localStorage.removeItem(REFERRAL_CODE_KEY);
        } catch {
          /* ignore */
        }
      })
      .catch((err) => {
        console.warn("claim-referral failed (will retry next visit)", err);
      });
  }, [isLoaded, isSignedIn]);

  return null;
}

/**
 * Resolves the Clerk session token onto the API client BEFORE rendering the
 * gated page content, so a page's first data fetch on cold load carries auth
 * instead of racing ClerkTokenSync (previously only the Overview page did this;
 * inner pages could fire a token-less first request). Only rendered when Clerk
 * is configured, so useAuth() is always inside <ClerkProvider>. Never acts on
 * isSignedIn before isLoaded — acting early bounces signed-in users to
 * /sign-in (the dashboard↔sign-in loop guarded against in ClerkAuthGuard).
 */
function ClerkTokenGate({ children }: { children: React.ReactNode }) {
  const { getToken, isSignedIn, isLoaded } = useAuth();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn) {
      // Not signed in: let ClerkAuthGuard handle the redirect; don't block here.
      setReady(true);
      return;
    }
    getToken()
      .then((token: string | null) => {
        if (token) api.setClerkToken(token);
      })
      .finally(() => setReady(true));
  }, [isLoaded, isSignedIn, getToken]);

  if (!ready) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          <Skeleton className="h-32 rounded-lg" />
          <Skeleton className="h-32 rounded-lg" />
          <Skeleton className="h-32 rounded-lg" />
        </div>
      </div>
    );
  }
  return <>{children}</>;
}

/**
 * The sidebar's contents — brand, nav sections, sign-out. Rendered both in the
 * static desktop aside and inside the mobile slide-in drawer. `onNavigate`
 * fires on link click so the mobile drawer can close itself.
 */
function SidebarBody({
  userEmail,
  isAdmin,
  pathname,
  onNavigate,
  onReplayTour,
}: {
  userEmail: string;
  isAdmin: boolean;
  pathname: string;
  onNavigate?: () => void;
  onReplayTour?: () => void;
}) {
  return (
    <>
      <div className="mb-6">
        <h1 className="flex items-center gap-2 text-xl font-serif font-semibold tracking-tight">
          <BeamLogo />
          Beam
        </h1>
        <p className="mt-1 truncate text-xs text-muted-foreground">{userEmail}</p>
      </div>
      <nav className="flex flex-1 flex-col gap-1">
        <p className="px-3 py-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          EasyTrack
        </p>
        {EASYTRACK_ITEMS.filter((item) => !item.adminOnly || isAdmin).map((item) => (
          <NavLink
            key={item.href}
            href={item.href}
            label={item.label}
            icon={item.icon}
            pathname={pathname}
            onNavigate={onNavigate}
            tour={item.tour}
          />
        ))}

        <Separator className="my-2" />

        <p className="px-3 py-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          EasyEngage
        </p>
        {EASYENGAGE_ITEMS.map((item) => (
          <NavLink
            key={item.href}
            href={item.href}
            label={item.label}
            icon={item.icon}
            pathname={pathname}
            onNavigate={onNavigate}
            tour={item.tour}
          />
        ))}

        <Separator className="my-2" />

        {GENERAL_ITEMS.map((item) => (
          <NavLink
            key={item.href}
            href={item.href}
            label={item.label}
            icon={item.icon}
            pathname={pathname}
            onNavigate={onNavigate}
            tour={item.tour}
          />
        ))}

        {/* One "Admin" tab → the hub that gathers every admin tool. */}
        {isAdmin && (
          <NavLink
            href={ADMIN_ITEM.href}
            label={ADMIN_ITEM.label}
            icon={ADMIN_ITEM.icon}
            pathname={pathname}
            onNavigate={onNavigate}
          />
        )}

        <div className="flex-1" />
      </nav>
      <Separator className="my-2" />
      <SidebarPlanBadge onNavigate={onNavigate} />
      {onReplayTour && (
        <Button
          variant="ghost"
          size="sm"
          className="justify-start gap-2 text-muted-foreground"
          onClick={() => {
            onNavigate?.();
            onReplayTour();
          }}
        >
          <HelpCircle className="h-4 w-4 shrink-0" />
          Help / Replay tour
        </Button>
      )}
      {HAS_CLERK ? <ClerkSignOutButton /> : <LegacySignOutButton />}
    </>
  );
}

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [tourOpen, setTourOpen] = useState(false);
  const autoLaunchTried = useRef(false);

  // Shared ["me"] cache with the Overview page — one /auth/me request, not two.
  const { data: me, isError: meError } = useQuery({
    queryKey: ["me"],
    queryFn: () => api.getMe(),
    staleTime: 5 * 60_000,
  });
  const userEmail = me?.email ?? "";
  const isAdmin = me?.is_admin === true;

  useEffect(() => {
    // Legacy auth (no Clerk): a missing token or a failed /me means re-login.
    // With Clerk, ClerkAuthGuard owns redirects.
    if (HAS_CLERK) return;
    if (!api.getToken() || meError) {
      api.clearToken();
      router.replace("/login");
    }
  }, [router, meError]);

  // During onboarding we strip the full nav: a half-finished setup that gets
  // interrupted by an accidental "Overview" click strands the user with no way
  // back to verification. Show only the brand + one deliberate exit instead.
  const isOnboarding = pathname === "/dashboard/onboarding";

  const completeTour = useCallback(() => {
    try {
      localStorage.setItem(TOUR_DONE_KEY, "1");
    } catch {
      /* storage blocked — tour will simply re-offer next session */
    }
  }, []);

  // Auto-launch the tour once on a user's first dashboard visit. Waits for
  // /auth/me so admin-only steps resolve and we know the session is authed
  // (getMe carries the token). Never runs on the onboarding setup flow.
  useEffect(() => {
    if (isOnboarding || !me || autoLaunchTried.current) return;
    autoLaunchTried.current = true;
    let done = false;
    try {
      done = localStorage.getItem(TOUR_DONE_KEY) === "1";
    } catch {
      return; // storage blocked — don't auto-launch
    }
    if (!done) setTourOpen(true);
  }, [me, isOnboarding]);

  if (isOnboarding) {
    return (
      <div className="flex min-h-screen flex-col">
        {HAS_CLERK && <ClerkAuthGuard />}
        <header className="flex items-center justify-between border-b border-border bg-card px-6 py-3">
          <h1 className="text-xl font-serif font-semibold tracking-tight flex items-center gap-2">
            <BeamLogo />
            Beam
          </h1>
          <Link
            href="/dashboard"
            onClick={() => {
              // Mark this as a deliberate exit so the dashboard's zero-site
              // auto-redirect doesn't bounce the user straight back here — the
              // trap that made "Exit to dashboard" a no-op for users who hadn't
              // created a site yet. Sticky for the tab session, not consumed on
              // first read, so repeat /dashboard visits stay reachable too.
              try {
                sessionStorage.setItem("beam_exit_onboarding", "1");
              } catch {
                /* storage blocked — redirect guard just won't apply */
              }
            }}
            className="text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            Exit to dashboard
          </Link>
        </header>
        <main className="flex-1 overflow-auto p-6">
          {HAS_CLERK ? <ClerkTokenGate>{children}</ClerkTokenGate> : children}
        </main>
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Clerk auth guard (only when Clerk is active) */}
      {HAS_CLERK && <ClerkAuthGuard />}

      {/* Desktop sidebar (md and up). Full viewport height + own scroll so it
          stays put while the main column scrolls — never slides off on scroll. */}
      <aside className="hidden w-56 shrink-0 flex-col overflow-y-auto border-r border-border bg-card p-4 md:flex">
        <SidebarBody
          userEmail={userEmail}
          isAdmin={isAdmin}
          pathname={pathname}
          onReplayTour={() => setTourOpen(true)}
        />
      </aside>

      {/* Mobile slide-in drawer (below md). Radix gives focus-trap, ESC and
          outside-click close for free; nav links close it via onNavigate. */}
      <DialogPrimitive.Root open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
        <DialogPrimitive.Portal>
          <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-foreground/40 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 md:hidden" />
          <DialogPrimitive.Content className="fixed inset-y-0 left-0 z-50 flex w-64 flex-col overflow-y-auto border-r border-border bg-card p-4 shadow-lg data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left md:hidden">
            <DialogPrimitive.Title className="sr-only">Navigation</DialogPrimitive.Title>
            <SidebarBody
              userEmail={userEmail}
              isAdmin={isAdmin}
              pathname={pathname}
              onNavigate={() => setMobileNavOpen(false)}
              onReplayTour={() => setTourOpen(true)}
            />
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
      </DialogPrimitive.Root>

      <div className="flex flex-1 flex-col">
        {/* Mobile top bar (below md) */}
        <header className="flex items-center gap-3 border-b border-border bg-card px-4 py-3 md:hidden">
          <button
            type="button"
            onClick={() => setMobileNavOpen(true)}
            aria-label="Open menu"
            className="inline-flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          >
            <Menu className="h-5 w-5" />
          </button>
          <span className="flex items-center gap-2 font-serif text-lg font-semibold tracking-tight">
            <BeamLogo />
            Beam
          </span>
        </header>

        <main className="bg-pixel-sky flex-1 overflow-auto p-6">
          {HAS_CLERK ? (
            <ClerkTokenGate>
              <ExpiringConnectionBanner />
              {children}
            </ClerkTokenGate>
          ) : (
            <>
              <ExpiringConnectionBanner />
              {children}
            </>
          )}
        </main>
      </div>

      <OnboardingTour
        steps={TOUR_STEPS}
        open={tourOpen}
        onOpenChange={setTourOpen}
        onComplete={completeTour}
        isAdmin={isAdmin}
      />
    </div>
  );
}
