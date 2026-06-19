"use client";

import { useEffect, useState } from "react";
import { api, Site } from "@/lib/api";
import { SelectSkeleton } from "@/components/skeletons";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface SiteSelectorProps {
  value: string;
  onChange: (siteId: string) => void;
}

// Each dashboard page keeps its own siteId state, so the selection is lost
// on navigation (e.g. visiting a visitor then coming back). Persist it here
// so every page restores the last-picked site instead of defaulting to s[0].
const STORAGE_KEY = "beam.selectedSite";

export function SiteSelector({ value, onChange }: SiteSelectorProps) {
  // null = still loading (render a skeleton, not nothing — the control
  // popping in shifted the page header)
  const [sites, setSites] = useState<Site[] | null>(null);

  // Persist every selection, then route the parent's onChange through it.
  const selectSite = (siteId: string) => {
    localStorage.setItem(STORAGE_KEY, siteId);
    onChange(siteId);
  };

  useEffect(() => {
    api.listSites().then((s) => {
      setSites(s);
      if (!value && s.length > 0) {
        // Restore the saved site if it still exists, else fall back to first.
        const saved = localStorage.getItem(STORAGE_KEY);
        const initial = saved && s.some((x) => x.site_id === saved) ? saved : s[0].site_id;
        selectSite(initial);
      }
    }).catch(() => setSites([]));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (sites === null) return <SelectSkeleton />;
  if (sites.length === 0) return null;

  return (
    <Select value={value} onValueChange={selectSite}>
      <SelectTrigger className="w-[200px]">
        <SelectValue placeholder="Select site" />
      </SelectTrigger>
      <SelectContent>
        {sites.map((site) => (
          <SelectItem key={site.site_id} value={site.site_id}>
            {site.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
