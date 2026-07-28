"use client";

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, Segment } from "@/lib/api";
import { SiteSelector } from "@/components/site-selector";
import { PageHeader } from "@/components/page-header";
import { ConnectorsHelp } from "@/components/page-help";
import { CrmConnectPanel } from "@/components/crm-connect-panel";
import { AdConnectPanel } from "@/components/ad-connect-panel";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const PLATFORMS = [
  { value: "meta", label: "Meta Custom Audiences" },
  { value: "google", label: "Google Customer Match" },
  { value: "linkedin", label: "LinkedIn Matched Audiences" },
];

// Sub-tabs the page exposes. Kept as a constant so a deep link like
// /dashboard/connectors?tab=import lands on the right pane.
const TABS = ["export", "connect", "import"] as const;
type ConnectorTab = (typeof TABS)[number];

export default function ConnectorsPage() {
  const searchParams = useSearchParams();
  const [siteId, setSiteId] = useState(searchParams.get("site") || "");

  const initialTab = searchParams.get("tab");
  const [tab, setTab] = useState<ConnectorTab>(
    TABS.includes(initialTab as ConnectorTab)
      ? (initialTab as ConnectorTab)
      : "export"
  );

  // ── Export state ──
  const [segments, setSegments] = useState<Segment[]>([]);
  const [selectedSegment, setSelectedSegment] = useState("");
  const [platform, setPlatform] = useState("meta");
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  // ── Import (known contacts) state ──
  const [knownCount, setKnownCount] = useState<number | null>(null);
  const [knownBusy, setKnownBusy] = useState(false);
  const [knownMsg, setKnownMsg] = useState<string | null>(null);
  const knownFileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!siteId) return;
    api.listSegments(siteId).then((r) => setSegments(r.segments)).catch(() => {});
    setKnownMsg(null);
    setKnownCount(null);
    api
      .getKnownCount(siteId)
      .then((r) => setKnownCount(r.count))
      .catch(() => {});
  }, [siteId]);

  async function handleExport() {
    if (!selectedSegment || !siteId) return;
    setDownloading(true);
    setDownloadError(null);
    try {
      await api.downloadExport(siteId, selectedSegment, platform);
    } catch (err) {
      setDownloadError(
        err instanceof Error ? err.message : "Failed to download export"
      );
    } finally {
      setDownloading(false);
    }
  }

  async function handleKnownUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // let the same file be re-selected
    if (!file || !siteId) return;
    setKnownBusy(true);
    setKnownMsg(null);
    try {
      const r = await api.uploadKnownContacts(siteId, file);
      setKnownMsg(
        `Added ${r.inserted} new, skipped ${r.skipped} already on file` +
          (r.truncated ? " (file truncated at 50,000)" : "") +
          "."
      );
      const c = await api.getKnownCount(siteId);
      setKnownCount(c.count);
    } catch (err) {
      setKnownMsg(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setKnownBusy(false);
    }
  }

  async function handleKnownClear() {
    if (!siteId) return;
    if (!window.confirm("Remove your entire known-contacts list for this site?")) return;
    setKnownBusy(true);
    setKnownMsg(null);
    try {
      const r = await api.clearKnownContacts(siteId);
      setKnownMsg(`Removed ${r.deleted} contacts.`);
      setKnownCount(0);
    } catch (err) {
      setKnownMsg(err instanceof Error ? err.message : "Failed to clear");
    } finally {
      setKnownBusy(false);
    }
  }

  return (
    <div className="max-w-lg space-y-6">
      <PageHeader
        title="Connectors"
        info={<ConnectorsHelp />}
        actions={<SiteSelector value={siteId} onChange={setSiteId} />}
      />

      <Tabs value={tab} onValueChange={(v) => setTab(v as ConnectorTab)}>
        <TabsList>
          <TabsTrigger value="export">Ad Audiences</TabsTrigger>
          <TabsTrigger value="connect">Connect CRM</TabsTrigger>
          <TabsTrigger value="import">Exclude List</TabsTrigger>
        </TabsList>

        {/* ── Export: download a CSV for an ad platform ── */}
        <TabsContent value="export" className="space-y-6">
          {/* Direct ad-platform push. There is no frontend feature-flag read
              pattern in this app, so the panel always renders and the backend
              returns a clean "not enabled" error when ad_audiences_enabled is
              off — see phase-1-foundation plan step E2. */}
          <AdConnectPanel siteId={siteId} segments={segments} />

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Export segment for ads</CardTitle>
              <CardDescription>
                Download a CSV file formatted for your ad platform.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">Segment</label>
                <Select value={selectedSegment} onValueChange={setSelectedSegment}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select segment" />
                  </SelectTrigger>
                  <SelectContent>
                    {segments.map((seg) => (
                      <SelectItem key={seg.id} value={seg.id}>
                        {seg.name} ({seg.visitor_count} visitors)
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium">Platform</label>
                <Select value={platform} onValueChange={setPlatform}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PLATFORMS.map((p) => (
                      <SelectItem key={p.value} value={p.value}>
                        {p.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <Button
                className="w-full"
                onClick={handleExport}
                disabled={!selectedSegment || downloading}
              >
                {downloading ? "Downloading..." : "Download CSV"}
              </Button>

              {downloadError && (
                <p className="text-sm text-destructive">{downloadError}</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Connect CRM: live sync to a CRM / webhook ── */}
        <TabsContent value="connect">
          <CrmConnectPanel siteId={siteId} segments={segments} />
        </TabsContent>

        {/* ── Import from CRM: known-contacts list (moved from Settings) ── */}
        <TabsContent value="import">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Known contacts</CardTitle>
              <CardDescription>
                Upload a CSV of people you already know: existing customers, prior
                leads, or a CRM export. Beam flags matching visitors as “Known” so
                you can filter them out of net-new targeting. Emails are stored
                hashed; we never keep your plaintext list.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {!siteId ? (
                <p className="text-sm text-muted-foreground">Select a site first.</p>
              ) : (
                <>
                  <p className="text-sm text-muted-foreground">
                    {knownCount === null
                      ? "Loading…"
                      : `${knownCount} contact${knownCount === 1 ? "" : "s"} on file`}
                  </p>
                  <input
                    ref={knownFileRef}
                    type="file"
                    accept=".csv,text/csv"
                    className="hidden"
                    onChange={handleKnownUpload}
                  />
                  <div className="flex items-center gap-3">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={knownBusy}
                      onClick={() => knownFileRef.current?.click()}
                    >
                      {knownBusy ? "Working…" : "Upload CSV"}
                    </Button>
                    {!!knownCount && (
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={knownBusy}
                        onClick={handleKnownClear}
                      >
                        Remove all
                      </Button>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    CSV with an email column (or one email per line). Matching is
                    case-insensitive.
                  </p>
                  {knownMsg && <p className="text-sm text-foreground">{knownMsg}</p>}
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
