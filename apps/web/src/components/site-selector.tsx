"use client";

import { useEffect, useState } from "react";
import { api, Site } from "@/lib/api";
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

export function SiteSelector({ value, onChange }: SiteSelectorProps) {
  const [sites, setSites] = useState<Site[]>([]);

  useEffect(() => {
    api.listSites().then((s) => {
      setSites(s);
      // Auto-select first site if none selected
      if (!value && s.length > 0) {
        onChange(s[0].site_id);
      }
    }).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (sites.length === 0) return null;

  return (
    <Select value={value} onValueChange={onChange}>
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
