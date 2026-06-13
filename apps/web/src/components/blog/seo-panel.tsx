"use client";

import {
  analyzeSeo,
  effectiveMeta,
  effectiveTitle,
  TITLE_MAX,
  META_MAX,
  type SeoInput,
} from "@/components/blog/seo-analysis";

const SITE_HOST = "getbeam.fyi";

function bandColor(band: "good" | "ok" | "poor"): string {
  if (band === "good") return "text-green-600";
  if (band === "ok") return "text-amber-600";
  return "text-red-600";
}

function truncate(value: string, max: number): string {
  if (value.length <= max) return value;
  return value.slice(0, max - 1).trimEnd() + "…";
}

/** A length bar: green in range, amber under, red over. */
function LengthMeter({ value, max, label }: { value: number; max: number; label: string }) {
  const pct = Math.min(100, Math.round((value / max) * 100));
  const over = value > max;
  const under = value > 0 && value < max * 0.5;
  const color = over ? "bg-red-500" : under ? "bg-amber-500" : "bg-green-500";
  return (
    <div>
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className={over ? "text-red-600" : "text-muted-foreground"}>
          {value} / {max}
        </span>
      </div>
      <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-secondary">
        <div className={`h-full ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function CheckRow({ pass, label }: { pass: boolean; label: string }) {
  return (
    <li className="flex items-start gap-2 text-sm">
      <span
        className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-bold text-white ${
          pass ? "bg-green-500" : "bg-[rgba(43,37,48,0.25)]"
        }`}
        aria-hidden
      >
        {pass ? "✓" : "✕"}
      </span>
      <span className={pass ? "text-foreground/80" : "text-muted-foreground"}>{label}</span>
    </li>
  );
}

export function SeoPanel({ input }: { input: SeoInput }) {
  const a = analyzeSeo(input);
  const serpTitle = truncate(effectiveTitle(input) || "Untitled post", 60);
  const serpDesc = truncate(
    effectiveMeta(input) || "Add an excerpt or meta description to control the snippet Google shows.",
    160
  );
  const slug = (input.slug.trim() || "your-post-slug").replace(/^\/+/, "");
  const bandLabel = a.band === "good" ? "Good" : a.band === "ok" ? "Needs polish" : "Needs work";

  return (
    <div className="space-y-5 rounded-xl border border-[rgba(43,37,48,0.08)] bg-card p-5">
      {/* Score */}
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          SEO score
        </p>
        <div className="text-right">
          <span className={`text-2xl font-semibold ${bandColor(a.band)}`}>{a.score}</span>
          <span className="text-sm text-muted-foreground">/100</span>
          <p className={`text-xs ${bandColor(a.band)}`}>{bandLabel}</p>
        </div>
      </div>

      {/* Google SERP preview */}
      <div>
        <p className="mb-2 text-xs font-medium text-muted-foreground">Google preview</p>
        <div className="rounded-lg border border-[rgba(43,37,48,0.08)] p-3">
          <p className="text-xs text-[#4d5156]">
            {SITE_HOST} <span className="text-[#5f6368]">›</span> blog <span className="text-[#5f6368]">›</span> {slug}
          </p>
          <p className="mt-0.5 text-[18px] leading-tight text-[#1a0dab]">{serpTitle}</p>
          <p className="mt-1 text-[13px] leading-snug text-[#4d5156]">{serpDesc}</p>
        </div>
      </div>

      {/* Length meters */}
      <div className="space-y-3">
        <LengthMeter value={a.titleLen} max={TITLE_MAX} label="SEO title length" />
        <LengthMeter value={a.metaLen} max={META_MAX} label="Meta description length" />
      </div>

      {/* Checklist */}
      <div>
        <p className="mb-2 text-xs font-medium text-muted-foreground">
          Checklist ({a.passed}/{a.total})
        </p>
        <ul className="space-y-1.5">
          {a.checks.map((c) => (
            <CheckRow key={c.id} pass={c.pass} label={c.label} />
          ))}
        </ul>
      </div>
    </div>
  );
}
