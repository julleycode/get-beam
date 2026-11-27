"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ClosedWonSeedSummary } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const META_RATIOS = ["0.01", "0.02", "0.03", "0.05", "0.10"];
const GOOGLE_EXPANSIONS = ["NARROW", "BALANCED", "BROAD"] as const;

/**
 * Closed-won seed + lookalike. Renders nothing when the feature flag is off
 * (the seed endpoint 404s) so the panel never shows a dead control.
 */
export function ClosedWonLookalikeCard({ siteId }: { siteId: string }) {
  const [seed, setSeed] = useState<ClosedWonSeedSummary | null>(null);
  const [hidden, setHidden] = useState(false);
  const [open, setOpen] = useState(false);
  const [provider, setProvider] = useState<"meta" | "google">("meta");
  const [country, setCountry] = useState("");
  const [ratio, setRatio] = useState("0.01");
  const [expansion, setExpansion] = useState<(typeof GOOGLE_EXPANSIONS)[number]>("BALANCED");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    try {
      setSeed(await api.getClosedWonSeed(siteId));
    } catch {
      setHidden(true);
    }
  }, [siteId]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleCsv(file: File) {
    setBusy(true);
    setMessage("");
    try {
      const res = await api.uploadClosedWonCsv(siteId, await file.text());
      setMessage(`Added ${res.upserted} contacts (${res.skipped_invalid} invalid, ${res.skipped_erased} erased).`);
      await load();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleCreate() {
    setBusy(true);
    setMessage("");
    try {
      const res = await api.createClosedWonLookalike(siteId, {
        provider,
        country: country.toUpperCase(),
        ...(provider === "meta" ? { ratio } : { expansion }),
      });
      if (res.error) {
        setMessage(res.error);
      } else {
        const parts = [
          res.reused ? "Using your existing lookalike." : "Lookalike created.",
          res.previous_lookalike_id
            ? `Your previous lookalike (${res.previous_lookalike_id}) is still in your ad account.`
            : "",
          res.warning,
        ];
        setMessage(parts.filter(Boolean).join(" "));
        setOpen(false);
      }
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Lookalike failed");
    } finally {
      setBusy(false);
    }
  }

  if (hidden || !seed) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Lookalikes from closed-won customers</CardTitle>
        <CardDescription>
          {seed.total} closed-won contacts ({seed.matched} matched to visitors, {seed.eligible} eligible after
          exclusions). Only hashed emails leave Beam.
        </CardDescription>
        {seed.needs_reconnect && (
          <CardDescription className="text-destructive">
            Reconnect your CRM to allow Beam to read closed-won deals.
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="flex flex-wrap items-center gap-2">
        <Label className="cursor-pointer">
          <span className="sr-only">Upload closed-won CSV</span>
          <Input
            type="file"
            accept=".csv,text/csv"
            disabled={busy}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) handleCsv(f);
            }}
          />
        </Label>
        <Button disabled={busy || seed.eligible === 0} onClick={() => setOpen(true)}>
          Create lookalike
        </Button>
        {message && <p className="w-full text-sm text-muted-foreground">{message}</p>}
      </CardContent>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create lookalike</DialogTitle>
            <DialogDescription>
              {provider === "google"
                ? "Google lookalikes are usable in Demand Gen campaigns only. EEA countries are not supported."
                : "Meta needs at least 100 matched people in the seed."}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            <Select value={provider} onValueChange={(v) => setProvider(v as "meta" | "google")}>
              <SelectTrigger>
                <SelectValue placeholder="Platform" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="meta">Meta</SelectItem>
                <SelectItem value="google">Google</SelectItem>
              </SelectContent>
            </Select>
            <div>
              <Label htmlFor="cw-country">Country (required, 2 letters)</Label>
              <Input
                id="cw-country"
                maxLength={2}
                value={country}
                onChange={(e) => setCountry(e.target.value.replace(/[^a-zA-Z]/g, ""))}
                placeholder="US"
              />
            </div>
            {provider === "meta" ? (
              <Select value={ratio} onValueChange={setRatio}>
                <SelectTrigger>
                  <SelectValue placeholder="Size" />
                </SelectTrigger>
                <SelectContent>
                  {META_RATIOS.map((r) => (
                    <SelectItem key={r} value={r}>
                      {Math.round(Number(r) * 100)}% of country
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <Select
                value={expansion}
                onValueChange={(v) => setExpansion(v as (typeof GOOGLE_EXPANSIONS)[number])}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Reach" />
                </SelectTrigger>
                <SelectContent>
                  {GOOGLE_EXPANSIONS.map((x) => (
                    <SelectItem key={x} value={x}>
                      {x.charAt(0) + x.slice(1).toLowerCase()}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button disabled={busy || country.length !== 2} onClick={handleCreate}>
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
