"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// The Settings tab was dissolved. Per-account config (API keys, plan/cancel)
// now lives on Billing; per-site config (pixel, cookie consent, pause, budget,
// remove pixel) moved into the Site settings dialog — the gear next to the site
// picker. This stub keeps old /dashboard/settings bookmarks from 404-ing.
export default function SettingsRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/dashboard/billing");
  }, [router]);
  return null;
}
