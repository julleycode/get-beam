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
  const [matchType, setMatchType] = useState<"contains" | "prefix" | "exact">("contains");
  const [pattern, setPattern] = useState("");
  const [valueUsd, setValueUsd] = useState("");
  const [repeatable, setRepeatable] = useState(false);
  const [saving, setSaving] = useState(false);
  const [busyGoalId, setBusyGoalId] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<{ id: string; name: string } | null>(null);
  const [deleting, setDeleting] = useState(false);

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
    setMatchType("contains");
    setPattern("");
    setValueUsd("");
    setRepeatable(false);
  }

  async function handleCreate() {
    setActionError(null);
    const payload: GoalCreatePayload = {
      name: goalName.trim(),
      match_type: matchType,
      pattern: pattern.trim(),
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
          description="Choose a site to see what your Beam campaigns actually convert."
        />
      ) : goalsLoading || reportLoading ? (
        <TableSkeleton cols={5} />
      ) : !hasGoals ? (
        <EmptyState
          icon={Target}
          title="Prove what Beam converts"
          description={
            'Define a conversion goal — like "visitor reached /thank-you" — and Beam ' +
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
                  Campaigns page — clicks and conversions land here.
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
                            {g.match_type}: {g.pattern}
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
                Goals match the page URL your visitors land on — your installed Beam
                pixel does the tracking. Conversions without a recent campaign click
                are counted as organic, so the attributed number stays honest.
              </p>
            </CardContent>
          </Card>
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
              disabled={saving || !goalName.trim() || !pattern.trim()}
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
    </div>
  );
}
