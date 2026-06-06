"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { api, Campaign } from "@/lib/api";
import { SiteSelector } from "@/components/site-selector";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

function statusVariant(status: string) {
  switch (status) {
    case "active": return "default" as const;
    case "approved": return "default" as const;
    case "completed": return "secondary" as const;
    case "paused": return "outline" as const;
    default: return "secondary" as const;
  }
}

export default function CampaignsPage() {
  const searchParams = useSearchParams();
  const [siteId, setSiteId] = useState(searchParams.get("site") || "");
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(false);

  function loadCampaigns() {
    if (!siteId) return;
    setLoading(true);
    api.listCampaigns(siteId).then((r) => setCampaigns(r.campaigns)).catch(() => {}).finally(() => setLoading(false));
  }

  useEffect(loadCampaigns, [siteId]);

  async function handleStatusChange(campaignId: string, newStatus: string) {
    try {
      await api.updateCampaignStatus(siteId, campaignId, newStatus);
      loadCampaigns();
    } catch {
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-serif font-semibold tracking-tight">Campaigns</h2>
        <SiteSelector value={siteId} onChange={setSiteId} />
      </div>

      {!siteId ? (
        <p className="text-muted-foreground">Select a site to view campaigns.</p>
      ) : loading ? (
        <p className="text-muted-foreground">Loading...</p>
      ) : campaigns.length === 0 ? (
        <p className="text-muted-foreground">
          No campaigns yet. Campaigns are auto-generated when segments are created.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Campaign</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Created</TableHead>
              <TableHead>Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {campaigns.map((c) => (
              <TableRow key={c.id}>
                <TableCell>
                  <Link
                    href={`/dashboard/campaigns/${c.id}?site=${siteId}`}
                    className="hover:underline font-medium"
                  >
                    {c.name}
                  </Link>
                </TableCell>
                <TableCell>
                  <Badge variant={statusVariant(c.status)}>{c.status}</Badge>
                </TableCell>
                <TableCell className="text-sm">
                  {new Date(c.created_at).toLocaleDateString()}
                </TableCell>
                <TableCell>
                  <div className="flex gap-2">
                    {c.status === "draft" && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleStatusChange(c.id, "approved")}
                      >
                        Approve
                      </Button>
                    )}
                    {c.status === "approved" && (
                      <Button
                        size="sm"
                        onClick={() => handleStatusChange(c.id, "active")}
                      >
                        Start
                      </Button>
                    )}
                    {c.status === "active" && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleStatusChange(c.id, "paused")}
                      >
                        Pause
                      </Button>
                    )}
                    {c.status === "paused" && (
                      <Button
                        size="sm"
                        onClick={() => handleStatusChange(c.id, "active")}
                      >
                        Resume
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
