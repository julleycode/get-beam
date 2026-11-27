"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { ExclusionReason, SiteExclusion } from "@/lib/api-types";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const REASONS: { value: ExclusionReason; label: string }[] = [
  { value: "customer", label: "Customer" },
  { value: "competitor", label: "Competitor" },
  { value: "other", label: "Other" },
];

/**
 * Company exclusion list: domains (customers, competitors) that must never
 * receive outreach, exports, or ad pushes. Matching visitors stay visible on
 * the Visitors page with an "Excluded" badge — they are not hidden.
 */
export function ExclusionsPanel({ siteId }: { siteId: string }) {
  const [items, setItems] = useState<SiteExclusion[] | null>(null);
  const [domain, setDomain] = useState("");
  const [company, setCompany] = useState("");
  const [reason, setReason] = useState<ExclusionReason>("customer");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function reload() {
    if (!siteId) return;
    try {
      setItems(await api.listExclusions(siteId));
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Could not load exclusions");
    }
  }

  useEffect(() => {
    setItems(null);
    setMsg(null);
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [siteId]);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!domain.trim()) return;
    setBusy(true);
    setMsg(null);
    try {
      await api.createExclusion(siteId, {
        domain: domain.trim(),
        reason,
        company_name: company.trim() || undefined,
      });
      setDomain("");
      setCompany("");
      await reload();
    } catch (err) {
      const m = err instanceof Error ? err.message : "Could not add";
      setMsg(
        m === "freemail_domain"
          ? "Free email domains (gmail.com, outlook.com…) can't be excluded — that would exclude everyone."
          : m === "public_suffix" || m === "invalid_domain"
            ? "Enter a company domain like acme.com."
            : m,
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(id: string) {
    setBusy(true);
    setMsg(null);
    try {
      await api.deleteExclusion(siteId, id);
      await reload();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Could not delete");
    } finally {
      setBusy(false);
    }
  }

  async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.importExclusions(siteId, file);
      setMsg(
        `Imported ${r.upserted} domain${r.upserted === 1 ? "" : "s"}` +
          (r.errors.length
            ? `; ${r.errors.length} row${r.errors.length === 1 ? "" : "s"} skipped (${r.errors
                .slice(0, 5)
                .map((x) => `row ${x.row}: ${x.error}`)
                .join(", ")}${r.errors.length > 5 ? ", …" : ""})`
            : "."),
      );
      await reload();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Import failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle className="text-base">Excluded companies</CardTitle>
        <CardDescription>
          Customers and competitors listed here never get outreach, exports, or ad
          pushes. Their visits still show on the Visitors page, marked Excluded.
          Subdomains match too (eu.acme.com matches acme.com).
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {!siteId ? (
          <p className="text-sm text-muted-foreground">Select a site first.</p>
        ) : (
          <>
            <form onSubmit={handleAdd} className="flex flex-wrap items-center gap-2">
              <input
                className="h-9 w-48 rounded-md border bg-background px-2 text-sm"
                placeholder="acme.com"
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
                aria-label="Domain"
              />
              <input
                className="h-9 w-40 rounded-md border bg-background px-2 text-sm"
                placeholder="Company (optional)"
                value={company}
                onChange={(e) => setCompany(e.target.value)}
                aria-label="Company name"
              />
              <select
                className="h-9 rounded-md border bg-background px-2 text-sm"
                value={reason}
                onChange={(e) => setReason(e.target.value as ExclusionReason)}
                aria-label="Reason"
              >
                {REASONS.map((r) => (
                  <option key={r.value} value={r.value}>
                    {r.label}
                  </option>
                ))}
              </select>
              <Button type="submit" size="sm" disabled={busy || !domain.trim()}>
                Add
              </Button>
              <input
                ref={fileRef}
                type="file"
                accept=".csv,text/csv"
                className="hidden"
                onChange={handleImport}
              />
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => fileRef.current?.click()}
              >
                Import CSV
              </Button>
            </form>
            <p className="text-xs text-muted-foreground">
              CSV columns: domain, company_name, reason (customer / competitor /
              other). Max 5,000 rows or 1 MB.
            </p>
            {msg && <p className="text-sm text-foreground">{msg}</p>}
            {items === null ? (
              <p className="text-sm text-muted-foreground">Loading…</p>
            ) : items.length === 0 ? (
              <p className="text-sm text-muted-foreground">No excluded companies yet.</p>
            ) : (
              <ul className="divide-y rounded-md border">
                {items.map((x) => (
                  <li key={x.id} className="flex items-center justify-between px-3 py-2 text-sm">
                    <span>
                      <span className="font-medium">{x.domain}</span>
                      {x.company_name && (
                        <span className="text-muted-foreground"> · {x.company_name}</span>
                      )}
                      <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase">
                        {x.reason}
                      </span>
                    </span>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy}
                      onClick={() => handleDelete(x.id)}
                    >
                      Remove
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
