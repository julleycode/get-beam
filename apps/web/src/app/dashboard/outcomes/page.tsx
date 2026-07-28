"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Target, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { ConversionGoal, GoalCreatePayload } from "@/lib/api-types";
import { TableSkeleton } from "@/components/skeletons";
import { SiteSelector } from "@/components/site-selector";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";
import { StatTile } from "@/components/stat-tile";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
import { InfoTooltip } from "@/components/ui/info-tooltip";
import { PeriodToggle, type Period } from "@/components/ui/period-toggle";
import { StatusBadge } from "@/components/ui/status-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const MATCH_TYPE_HELP: Record<string, string> = {
  contains: "URL path contains this text",
  prefix: "URL path starts with this",
  exact: "URL path is exactly this",
};

function usd(cents: number): string {
  return `$${(cents / 100).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

async function copyText(text: string, flag: (v: boolean) => void) {
  try {
    await navigator.clipboard.writeText(text);
    flag(true);
    setTimeout(() => flag(false), 1500);
  } catch {
    // clipboard unavailable (permissions/http) — silently ignore
  }
}

export default function OutcomesPage() {
  const searchParams = useSearchParams();
  const [siteId, setSiteId] = useState(searchParams.get("site") || "");
  const [period, setPeriod] = useState<Period>("30d");
  // The report endpoint caps `days` at 365, so "lifetime" = the last year.
  const days = period === "lifetime" ? 365 : 30;
  const queryClient = useQueryClient();

  const [actionError, setActionError] = useState<string | null>(null);
  const [showNewGoal, setShowNewGoal] = useState(false);
  const [goalName, setGoalName] = useState("");
  const [goalType, setGoalType] = useState<"url_match" | "js_event">("url_match");
  const [matchType, setMatchType] = useState<"contains" | "prefix" | "exact">("contains");
  const [pattern, setPattern] = useState("");
  const [valueUsd, setValueUsd] = useState("");
  const [repeatable, setRepeatable] = useState(false);
  const [saving, setSaving] = useState(false);
  const [busyGoalId, setBusyGoalId] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<{ id: string; name: string } | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [revealedSecret, setRevealedSecret] = useState<string | null>(null);
  const [copiedSnippet, setCopiedSnippet] = useState(false);
  const [copiedSecret, setCopiedSecret] = useState(false);
  const [copiedCurl, setCopiedCurl] = useState(false);

  const { data: report, isLoading: reportLoading } = useQuery({
    queryKey: ["outcomes-report", siteId, days],
    queryFn: () => api.getOutcomesReport(siteId, days),
    enabled: !!siteId,
  });
  const { data: goalsData, isLoading: goalsLoading } = useQuery({
    queryKey: ["conversion-goals", siteId],
    queryFn: () => api.getConversionGoals(siteId),
    enabled: !!siteId,
  });
  const { data: webhookConfig } = useQuery({
    queryKey: ["outcomes-webhook-config", siteId],
    queryFn: () => api.getOutcomesWebhookConfig(siteId),
    enabled: !!siteId,
  });

  const goals = goalsData?.goals ?? [];
  const countsByGoal = new Map(
    (report?.goals ?? []).map((g) => [g.goal_id, g])
  );

  function reload() {
    queryClient.invalidateQueries({ queryKey: ["outcomes-report", siteId] });
    queryClient.invalidateQueries({ queryKey: ["conversion-goals", siteId] });
  }

  function resetForm() {
    setGoalName("");
    setGoalType("url_match");
    setMatchType("contains");
    setPattern("");
    setValueUsd("");
    setRepeatable(false);
  }

  async function handleCreate() {
    setActionError(null);
    const payload: GoalCreatePayload = {
      name: goalName.trim(),
      goal_type: goalType,
      match_type: matchType,
      pattern: goalType === "js_event" ? "" : pattern.trim(),
      repeatable,
    };
    if (valueUsd.trim()) {
      const parsed = Number(valueUsd);
      if (Number.isNaN(parsed) || parsed < 0) {
        setActionError("Value must be a positive number (in USD).");
        return;
      }
      payload.value_cents = Math.round(parsed * 100);
    }
    setSaving(true);
    try {
      await api.createConversionGoal(siteId, payload);
      setShowNewGoal(false);
      resetForm();
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Could not create goal");
    } finally {
      setSaving(false);
    }
  }

  async function handleToggle(goal: ConversionGoal) {
    setActionError(null);
    setBusyGoalId(goal.id);
    try {
      await api.updateConversionGoal(siteId, goal.id, { enabled: !goal.enabled });
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Could not update goal");
    } finally {
      setBusyGoalId(null);
    }
  }

  async function handleRotate() {
    setActionError(null);
    setRotating(true);
    try {
      const result = await api.rotateOutcomesWebhookSecret(siteId);
      setRevealedSecret(result.secret);
      queryClient.invalidateQueries({ queryKey: ["outcomes-webhook-config", siteId] });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Could not generate secret");
    } finally {
      setRotating(false);
    }
  }

  async function handleDelete() {
    if (!confirmDelete) return;
    setActionError(null);
    setDeleting(true);
    try {
      await api.deleteConversionGoal(siteId, confirmDelete.id);
      setConfirmDelete(null);
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Could not delete goal");
    } finally {
      setDeleting(false);
    }
  }

  const totals = report?.totals;
  const hasGoals = goals.length > 0;
  const exampleGoal =
    goals.find((g) => g.goal_type === "js_event")?.name ?? goals[0]?.name ?? "Purchase";
  const jsSnippet = `beamConvert("${exampleGoal}", { value: 49.99 })`;
  const curlSample =
    revealedSecret && webhookConfig
      ? [
          `BODY='{"goal":"${exampleGoal}","email":"customer@example.com","value":49.99,"event_id":"order_123"}'`,
          `SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "${revealedSecret}" -hex | awk '{print $NF}')`,
          `curl -X POST ${webhookConfig.url} \\`,
          `  -H "X-Beam-Signature: $SIG" -H "Content-Type: application/json" -d "$BODY"`,
        ].join("\n")
      : "";

  return (
    <div>
      <PageHeader
        title="Outcomes"
        actions={
          <div className="flex items-center gap-3">
            {hasGoals && <PeriodToggle value={period} onChange={setPeriod} />}
            <SiteSelector value={siteId} onChange={setSiteId} />
          </div>
        }
      />

      {actionError && (
        <p className="mb-4 text-sm text-destructive" role="alert">
          {actionError}
        </p>
      )}

      {!siteId ? (
        <EmptyState
          icon={Target}
          title="Pick a site"
          description="Choose a site to see what your Beam campaigns convert."
        />
      ) : goalsLoading || reportLoading ? (
        <TableSkeleton cols={5} />
      ) : !hasGoals ? (
        <EmptyState
          icon={Target}
          title="Prove what Beam converts"
          description={
            'Define a conversion goal (like "visitor reached /thank-you") and Beam ' +
            "will report how many conversions each campaign drove. Your installed " +
            "pixel does the tracking; nothing new to add to your site."
          }
          action={
            <Button onClick={() => setShowNewGoal(true)}>
              <Plus className="mr-1.5 h-4 w-4" />
              Create your first goal
            </Button>
          }
        />
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 rounded-lg border border-border bg-card p-4 md:grid-cols-4">
            <StatTile label="Conversions" value={totals?.conversions ?? 0} />
            <StatTile
              label="From Beam campaigns"
              value={
                <span className="inline-flex items-center gap-1.5">
                  {totals?.attributed ?? 0}
                  <InfoTooltip label="About attribution">
                    Counted when the converting visitor clicked a Beam campaign
                    link within the last 30 days. Email opens alone never count.
                  </InfoTooltip>
                </span>
              }
              tone="primary"
            />
            <StatTile
              label="Attributed revenue"
              value={usd(totals?.attributed_revenue_cents ?? 0)}
              tone="success"
            />
            <StatTile label="Organic (baseline)" value={totals?.organic ?? 0} />
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">By campaign</CardTitle>
            </CardHeader>
            <CardContent>
              {(report?.campaigns ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No campaign activity in this period yet. Start a beam from the
                  Campaigns page. Clicks and conversions land here.
                </p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Campaign</TableHead>
                      <TableHead className="text-right">Sent</TableHead>
                      <TableHead className="text-right">Clicked</TableHead>
                      <TableHead className="text-right">Converted</TableHead>
                      <TableHead className="text-right">Conv. rate</TableHead>
                      <TableHead className="text-right">Revenue</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(report?.campaigns ?? []).map((c) => (
                      <TableRow key={c.campaign_id}>
                        <TableCell>
                          <Link
                            href={`/dashboard/campaigns/${c.campaign_id}?site=${siteId}`}
                            className="font-medium hover:underline"
                          >
                            {c.name}
                          </Link>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{c.sent}</TableCell>
                        <TableCell className="text-right tabular-nums">{c.clicked}</TableCell>
                        <TableCell className="text-right font-medium tabular-nums text-primary">
                          {c.converted}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {c.sent ? `${(c.conversion_rate * 100).toFixed(1)}%` : "—"}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {c.revenue_cents ? usd(c.revenue_cents) : "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0">
              <CardTitle className="text-sm">Goals</CardTitle>
              <Button size="sm" variant="outline" onClick={() => setShowNewGoal(true)}>
                <Plus className="mr-1.5 h-4 w-4" />
                New goal
              </Button>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Goal</TableHead>
                    <TableHead>Rule</TableHead>
                    <TableHead className="text-right">Conversions</TableHead>
                    <TableHead className="text-right">Revenue</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {goals.map((g) => {
                    const counts = countsByGoal.get(g.id);
                    return (
                      <TableRow key={g.id}>
                        <TableCell className="font-medium">{g.name}</TableCell>
                        <TableCell className="text-muted-foreground">
                          <span className="font-mono text-xs">
                            {g.goal_type === "js_event"
                              ? "beamConvert() / webhook"
                              : `${g.match_type}: ${g.pattern}`}
                          </span>
                          {g.value_cents ? (
                            <span className="ml-2 text-xs">({usd(g.value_cents)} each)</span>
                          ) : null}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {counts?.conversions ?? 0}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {counts?.revenue_cents ? usd(counts.revenue_cents) : "—"}
                        </TableCell>
                        <TableCell>
                          <StatusBadge status={g.enabled ? "active" : "paused"} />
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-1.5">
                            <Button
                              size="sm"
                              variant="ghost"
                              disabled={busyGoalId === g.id}
                              onClick={() => handleToggle(g)}
                            >
                              {g.enabled ? "Disable" : "Enable"}
                            </Button>
                            <IconButton
                              label={`Delete ${g.name}`}
                              onClick={() => setConfirmDelete({ id: g.id, name: g.name })}
                            >
                              <Trash2 className="h-4 w-4" />
                            </IconButton>
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
              <p className="mt-3 text-xs text-muted-foreground">
                Goals match the page URL your visitors land on. Your installed Beam
                pixel does the tracking. Conversions without a recent campaign click
                are counted as organic, so the attributed number stays honest.
              </p>
            </CardContent>
          </Card>

          <div className="grid gap-6 md:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Track revenue from your site</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <p className="text-xs text-muted-foreground">
                  Call this on your success page or after checkout. The goal name
                  must match a goal above; the value lands as revenue on the
                  campaign that drove the buyer.
                </p>
                <div className="relative">
                  <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-md bg-muted p-3 text-xs">
                    {jsSnippet}
                  </pre>
                  <Button
                    variant="outline"
                    size="sm"
                    className="absolute right-2 top-2"
                    onClick={() => copyText(jsSnippet, setCopiedSnippet)}
                  >
                    {copiedSnippet ? "Copied!" : "Copy"}
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Works anywhere the Beam pixel is installed. No extra script.
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Send conversions from your server</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-xs text-muted-foreground">
                  For Stripe, Zapier, or your backend: POST conversions (with an
                  email or visitor id) to your signed webhook. Beam matches the
                  person and attributes the campaign.
                </p>
                {webhookConfig?.configured ? (
                  <div className="space-y-2 text-xs">
                    <p className="break-all font-mono text-muted-foreground">
                      {webhookConfig.url}
                    </p>
                    <p className="text-muted-foreground">
                      Secret: <span className="font-mono">{webhookConfig.hint}</span>{" "}
                      (shown once at creation)
                    </p>
                    <Button size="sm" variant="outline" disabled={rotating} onClick={handleRotate}>
                      {rotating ? "Rotating…" : "Rotate secret"}
                    </Button>
                    <p className="text-muted-foreground">
                      Rotating invalidates the current secret immediately.
                    </p>
                  </div>
                ) : (
                  <Button size="sm" disabled={rotating} onClick={handleRotate}>
                    {rotating ? "Generating…" : "Generate webhook secret"}
                  </Button>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      <Dialog open={showNewGoal} onOpenChange={(open) => !open && setShowNewGoal(false)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New conversion goal</DialogTitle>
            <DialogDescription>
              When a visitor lands on a matching page, Beam records a conversion and
              credits the campaign they came from.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="goal-name">
                Name
              </label>
              <Input
                id="goal-name"
                placeholder="Signup"
                value={goalName}
                onChange={(e) => setGoalName(e.target.value)}
                maxLength={100}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="goal-type">
                Tracked via
              </label>
              <select
                id="goal-type"
                className="h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm"
                value={goalType}
                onChange={(e) => setGoalType(e.target.value as "url_match" | "js_event")}
              >
                <option value="url_match">Page URL (no code needed)</option>
                <option value="js_event">beamConvert() / server webhook</option>
              </select>
            </div>
            {goalType === "url_match" && (
              <div className="space-y-1.5">
                <label className="text-sm font-medium" htmlFor="goal-match">
                  Rule
                </label>
                <div className="flex gap-2">
                  <select
                    id="goal-match"
                    className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
                    value={matchType}
                    onChange={(e) =>
                      setMatchType(e.target.value as "contains" | "prefix" | "exact")
                    }
                  >
                    <option value="contains">contains</option>
                    <option value="prefix">starts with</option>
                    <option value="exact">exactly</option>
                  </select>
                  <Input
                    placeholder={matchType === "contains" ? "thank-you" : "/thank-you"}
                    value={pattern}
                    onChange={(e) => setPattern(e.target.value)}
                    maxLength={500}
                  />
                </div>
                <p className="text-xs text-muted-foreground">{MATCH_TYPE_HELP[matchType]}.</p>
              </div>
            )}
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="goal-value">
                Value per conversion (USD, optional)
              </label>
              <Input
                id="goal-value"
                type="number"
                min="0"
                step="0.01"
                placeholder="49"
                value={valueUsd}
                onChange={(e) => setValueUsd(e.target.value)}
              />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={repeatable}
                onChange={(e) => setRepeatable(e.target.checked)}
                className="h-4 w-4 rounded border-input"
              />
              Can happen more than once per visitor (e.g. purchases)
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowNewGoal(false)} disabled={saving}>
              Cancel
            </Button>
            <Button
              onClick={handleCreate}
              disabled={
                saving ||
                !goalName.trim() ||
                (goalType === "url_match" && !pattern.trim())
              }
            >
              {saving ? "Creating…" : "Create goal"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={!!confirmDelete}
        onOpenChange={(open) => !open && setConfirmDelete(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete “{confirmDelete?.name}”?</DialogTitle>
            <DialogDescription>
              This also deletes every conversion recorded for this goal. Campaign
              outcome numbers will drop accordingly. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmDelete(null)} disabled={deleting}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
              {deleting ? "Deleting…" : "Delete goal"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={!!revealedSecret}
        onOpenChange={(open) => !open && setRevealedSecret(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Your webhook secret</DialogTitle>
            <DialogDescription>
              Copy it now. Beam stores it encrypted and can never show it again.
              Sign every request body with HMAC-SHA256 using this secret.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="relative">
              <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-md bg-muted p-3 text-xs">
                {revealedSecret}
              </pre>
              <Button
                variant="outline"
                size="sm"
                className="absolute right-2 top-2"
                onClick={() => revealedSecret && copyText(revealedSecret, setCopiedSecret)}
              >
                {copiedSecret ? "Copied!" : "Copy"}
              </Button>
            </div>
            <p className="text-xs font-medium">Test it:</p>
            <div className="relative">
              <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-md bg-muted p-3 text-xs">
                {curlSample}
              </pre>
              <Button
                variant="outline"
                size="sm"
                className="absolute right-2 top-2"
                onClick={() => copyText(curlSample, setCopiedCurl)}
              >
                {copiedCurl ? "Copied!" : "Copy"}
              </Button>
            </div>
          </div>
          <DialogFooter>
            <Button onClick={() => setRevealedSecret(null)}>Done, I copied it</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
