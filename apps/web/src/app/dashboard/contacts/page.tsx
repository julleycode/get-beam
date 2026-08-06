"use client";

/**
 * Imported Contacts — bring your own list in as contactable leads.
 *
 * DELIBERATELY a separate top-level route from /dashboard/connectors?tab=import,
 * which hosts the structurally different "Known contacts" upload (a hash-only
 * exclusion filter that creates no visitors and stores no plaintext email).
 * The two surfaces both say "upload a CSV of contacts" but do opposite things,
 * so they are kept apart at the navigation level, not just in copy.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  api,
  HotImportedContactsSummary,
  ImportContactsResult,
  ImportedContact,
} from "@/lib/api";
import { SiteSelector } from "@/components/site-selector";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function ImportedContactsPage() {
  const searchParams = useSearchParams();
  const [siteId, setSiteId] = useState(searchParams.get("site") || "");

  const [contacts, setContacts] = useState<ImportedContact[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [limit, setLimit] = useState(5000);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ImportContactsResult | null>(null);
  const [hot, setHot] = useState<HotImportedContactsSummary | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    if (!siteId) return;
    try {
      const r = await api.listImportedContacts(siteId);
      setContacts(r.contacts);
      setTotal(r.total);
      setLimit(r.limit);
    } catch {
      // A load failure leaves the previous list visible; the upload path owns
      // the user-facing error surface.
    }
    try {
      setHot(await api.getHotImportedContacts(siteId));
    } catch {
      // The activity summary is additive — a failure here hides the widget
      // rather than breaking the import surface.
      setHot(null);
    }
  }, [siteId]);

  useEffect(() => {
    setError(null);
    setResult(null);
    setContacts([]);
    setTotal(null);
    setHot(null);
    load();
  }, [siteId, load]);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-uploading the same filename
    if (!file || !siteId) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.importContacts(siteId, file));
      await load();
    } catch (err) {
      // Surfaces the 5,000-contact cap message and the defensive file/row caps.
      setError(err instanceof Error ? err.message : "Import failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Imported Contacts"
        info="Contacts you uploaded yourself — real, contactable leads with tracking links. Not the same as the hash-only “Known contacts” filter under Connectors → Import."
      />

      <SiteSelector value={siteId} onChange={setSiteId} />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Import contacts as leads</CardTitle>
          <CardDescription>
            Upload a CSV (columns: name, email) of contacts you already own. Each
            row becomes a real lead with its own tracking link, so you can reach
            them through your normal campaign approval flow before they ever
            visit your site.
            <br />
            <span className="text-muted-foreground">
              This is <strong>not</strong> the “Known contacts” upload under
              Connectors → Import. That one is a hash-only filter used to mark
              existing customers so you can exclude them — it never creates a
              contact or keeps an email address. This one does the opposite: it
              creates contactable leads.
            </span>
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {!siteId ? (
            <p className="text-sm text-muted-foreground">Select a site first.</p>
          ) : (
            <>
              <p className="text-sm text-muted-foreground">
                {total === null
                  ? "Loading…"
                  : `${total} of ${limit} imported contacts used`}
              </p>
              <input
                ref={fileRef}
                type="file"
                accept=".csv,text/csv"
                className="hidden"
                onChange={handleUpload}
              />
              <Button
                onClick={() => fileRef.current?.click()}
                disabled={busy}
              >
                {busy ? "Importing…" : "Upload CSV"}
              </Button>

              {error && (
                <p className="text-sm text-destructive" role="alert">
                  {error}
                </p>
              )}
              {result && (
                <div className="text-sm space-y-1">
                  <p>
                    Imported {result.imported} contact
                    {result.imported === 1 ? "" : "s"}
                    {result.rejected > 0 ? `, skipped ${result.rejected}` : ""}.
                  </p>
                  {result.rejected_rows.length > 0 && (
                    <ul className="text-muted-foreground list-disc pl-5">
                      {result.rejected_rows.slice(0, 5).map((r, i) => (
                        <li key={i}>
                          {r.line !== null ? `Row ${r.line}: ` : ""}
                          {r.reason}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {siteId && hot && hot.total_count > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {hot.active_count} of your {hot.total_count} imported contacts
              active this week
            </CardTitle>
            <CardDescription>
              An imported contact counts as active once one of their real visits
              has been matched to them — in the last {hot.window_days} days.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {hot.contacts.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                None of your imported contacts have visited in the last{" "}
                {hot.window_days} days yet.
              </p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-muted-foreground">
                    <th className="py-2">Name</th>
                    <th className="py-2">Email</th>
                    <th className="py-2">Last activity</th>
                  </tr>
                </thead>
                <tbody>
                  {hot.contacts.map((c) => (
                    <tr key={c.visitor_id} className="border-t">
                      <td className="py-2">{c.full_name || "—"}</td>
                      <td className="py-2">{c.email || "—"}</td>
                      <td className="py-2">
                        {c.last_activity_at
                          ? new Date(c.last_activity_at).toLocaleString()
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      )}

      {siteId && contacts.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Your imported contacts</CardTitle>
            <CardDescription>
              Link status shows whether a tracking link could be generated for
              this contact.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted-foreground">
                  <th className="py-2">Name</th>
                  <th className="py-2">Email</th>
                  <th className="py-2">Status</th>
                  <th className="py-2">Link</th>
                </tr>
              </thead>
              <tbody>
                {contacts.map((c) => (
                  <tr key={c.visitor_id} className="border-t">
                    <td className="py-2">{c.full_name || "—"}</td>
                    <td className="py-2">{c.email || "—"}</td>
                    <td className="py-2">{c.identity_status}</td>
                    <td className="py-2">{c.has_link ? "Ready" : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
