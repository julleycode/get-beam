"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, Copy, Gift, UserPlus, Zap } from "lucide-react";
import { api } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";
import { StatTile } from "@/components/stat-tile";
import { ErrorBanner } from "@/components/error-banner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/status-badge";

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

export default function ReferralsPage() {
  const [copied, setCopied] = useState(false);
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["referral-info"],
    queryFn: () => api.getReferralInfo(),
  });

  async function copyLink() {
    if (!data) return;
    try {
      await navigator.clipboard.writeText(data.link);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard unavailable (permissions/http) — silently ignore
    }
  }

  return (
    <div>
      <PageHeader title="Referrals" />

      {error ? (
        <ErrorBanner
          message="Could not load your referral info. Please try again."
          onRetry={() => refetch()}
        />
      ) : null}

      {isLoading || !data ? (
        <div className="space-y-4">
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Gift className="h-4 w-4 text-primary" />
                Give quota, get quota
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Know someone else doing growth or sales? When they sign up with
                your link and their pixel records its first visitors, you{" "}
                <strong className="text-foreground">
                  both earn +{data.bonus_per_activation} identified
                  visitors/month
                </strong>
                , permanently, up to +{data.bonus_cap}.
              </p>
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input
                  readOnly
                  value={data.link}
                  className="font-mono text-xs"
                  onFocus={(e) => e.currentTarget.select()}
                />
                <Button onClick={copyLink} className="shrink-0">
                  {copied ? (
                    <>
                      <Check className="mr-1.5 h-4 w-4" /> Copied
                    </>
                  ) : (
                    <>
                      <Copy className="mr-1.5 h-4 w-4" /> Copy link
                    </>
                  )}
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="grid grid-cols-3 gap-4 py-6">
              <StatTile label="Referred" value={data.referred_count} />
              <StatTile
                label="Activated"
                value={data.activated_count}
                tone={data.activated_count > 0 ? "success" : "default"}
              />
              <StatTile
                label={`Bonus (of +${data.bonus_cap} max)`}
                value={`+${data.bonus_monthly_quota}/mo`}
                tone={data.bonus_monthly_quota > 0 ? "primary" : "default"}
              />
            </CardContent>
          </Card>

          {data.referrals.length === 0 ? (
            <EmptyState
              icon={UserPlus}
              title="No referrals yet"
              description="Share your link with other founders and growth folks. A referral from someone who ships is worth more than any ad."
            />
          ) : (
            <Card>
              <CardHeader>
                <CardTitle>Your referrals</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="divide-y divide-border">
                  {data.referrals.map((r, i) => (
                    <li
                      key={`${r.email_masked}-${i}`}
                      className="flex items-center justify-between gap-3 py-2.5 text-sm"
                    >
                      <span className="font-mono text-xs">{r.email_masked}</span>
                      <span className="flex items-center gap-3">
                        <span className="text-xs text-muted-foreground">
                          {r.status === "activated"
                            ? `activated ${fmtDate(r.activated_at)}`
                            : `signed up ${fmtDate(r.signed_up_at)}`}
                        </span>
                        <StatusBadge
                          status={r.status}
                          tone={r.status === "activated" ? "success" : "warning"}
                        />
                      </span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Zap className="h-4 w-4 text-primary" />
                How it works
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ol className="list-decimal space-y-1.5 pl-5 text-sm text-muted-foreground">
                <li>Send your link to someone who&apos;d want to see their visitors.</li>
                <li>They create an account through it and install the Beam pixel.</li>
                <li>
                  The moment their pixel records real traffic, you both get +
                  {data.bonus_per_activation} identified visitors/month for
                  good. No cash, no coupons, just more Beam.
                </li>
              </ol>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
