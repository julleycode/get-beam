"use client";

import { useEffect, useState, type ComponentType } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Plus,
  Settings2,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { KpiStrip } from "@/components/kpi-strip";
import { TrafficFitCard } from "@/components/traffic-fit-card";
import { BrowserCaptureCard } from "@/components/browser-capture-card";

type WidgetId = "funnel" | "traffic_fit" | "browser";

type WidgetDef = {
  id: WidgetId;
  label: string;
  Component: ComponentType<{ siteId: string }>;
};

// The catalogue of widgets a user can show on the Visitors page. Add new
// insight cards here and they become available in the "Add widget" picker.
const REGISTRY: WidgetDef[] = [
  { id: "funnel", label: "Funnel", Component: KpiStrip },
  { id: "traffic_fit", label: "Traffic fit", Component: TrafficFitCard },
  { id: "browser", label: "Capture by browser", Component: BrowserCaptureCard },
];

const DEFAULT_LAYOUT: WidgetId[] = ["funnel", "traffic_fit", "browser"];
const LAYOUT_KEY = "beam_visitor_widgets_v1";

const isWidgetId = (s: string): s is WidgetId =>
  REGISTRY.some((w) => w.id === s);

/**
 * Customizable widget grid for the Visitors page. Users add / remove / reorder
 * the insight cards; the layout (ordered list of widget ids) persists in
 * localStorage so it survives reloads. Per-browser for now — a backend sync
 * could replace the storage layer without touching this UI.
 */
export function VisitorWidgets({ siteId }: { siteId: string }) {
  const [layout, setLayout] = useState<WidgetId[]>(DEFAULT_LAYOUT);
  const [editing, setEditing] = useState(false);
  const [addOpen, setAddOpen] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(LAYOUT_KEY);
      if (raw) {
        // Keep only ids that still exist in the registry (a removed widget in
        // saved layout must not crash render), preserve the saved order.
        const ids = (JSON.parse(raw) as string[]).filter(isWidgetId);
        setLayout(ids as WidgetId[]);
      }
    } catch {
      /* corrupt / blocked storage — keep the default layout */
    }
  }, []);

  const persist = (next: WidgetId[]) => {
    setLayout(next);
    try {
      localStorage.setItem(LAYOUT_KEY, JSON.stringify(next));
    } catch {
      /* storage blocked — keep it in-memory for this session */
    }
  };

  const remove = (id: WidgetId) => persist(layout.filter((x) => x !== id));
  const addWidget = (id: WidgetId) => {
    persist([...layout, id]);
    setAddOpen(false);
  };
  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= layout.length) return;
    const next = [...layout];
    [next[i], next[j]] = [next[j], next[i]];
    persist(next);
  };

  if (!siteId) return null;

  const hidden = REGISTRY.filter((w) => !layout.includes(w.id));

  return (
    <div className="mb-6 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Insights
        </span>
        <Button
          variant={editing ? "default" : "ghost"}
          size="sm"
          onClick={() => {
            setEditing((e) => !e);
            setAddOpen(false);
          }}
        >
          {editing ? (
            <>
              <Check className="mr-1 h-3.5 w-3.5" />
              Done
            </>
          ) : (
            <>
              <Settings2 className="mr-1 h-3.5 w-3.5" />
              Customize
            </>
          )}
        </Button>
      </div>

      <div className="grid items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
        {layout.map((id, i) => {
          const w = REGISTRY.find((x) => x.id === id);
          if (!w) return null;
          const { Component } = w;
          return (
            <div
              key={id}
              className={cn(
                editing &&
                  "min-h-[88px] overflow-hidden rounded-lg ring-2 ring-primary/30"
              )}
            >
              {editing && (
                // In-flow control bar (not an absolute overlay): never collides
                // with a widget's own header toggles, and stays visible+labeled
                // even when the widget renders nothing (no data) so it's still
                // removable.
                <div className="flex items-center justify-between gap-2 border-b border-border bg-secondary/40 px-2 py-1">
                  <span className="truncate text-xs font-medium text-muted-foreground">
                    {w.label}
                  </span>
                  <div className="flex shrink-0 items-center gap-0.5">
                    <button
                      type="button"
                      onClick={() => move(i, -1)}
                      disabled={i === 0}
                      aria-label={`Move ${w.label} left`}
                      className="flex h-6 w-6 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-30"
                    >
                      <ArrowLeft className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => move(i, 1)}
                      disabled={i === layout.length - 1}
                      aria-label={`Move ${w.label} right`}
                      className="flex h-6 w-6 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-30"
                    >
                      <ArrowRight className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => remove(id)}
                      aria-label={`Remove ${w.label}`}
                      className="flex h-6 w-6 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              )}
              <Component siteId={siteId} />
            </div>
          );
        })}

        {editing && hidden.length > 0 && (
          <div className="relative">
            {!addOpen ? (
              <button
                type="button"
                onClick={() => setAddOpen(true)}
                className="flex h-full min-h-[140px] w-full flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-border text-muted-foreground transition-colors hover:border-primary hover:text-foreground"
              >
                <Plus className="h-5 w-5" />
                <span className="text-sm font-medium">Add widget</span>
              </button>
            ) : (
              <div className="rounded-lg border border-border bg-card p-1.5 shadow-sm">
                <p className="px-2 py-1 text-xs text-muted-foreground">
                  Add a widget
                </p>
                {hidden.map((w) => (
                  <button
                    key={w.id}
                    type="button"
                    onClick={() => addWidget(w.id)}
                    className="block w-full rounded px-2 py-1.5 text-left text-sm transition-colors hover:bg-secondary"
                  >
                    {w.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {editing && layout.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No widgets shown. Use{" "}
          <span className="font-medium text-foreground">Add widget</span> to bring
          some back.
        </p>
      )}
    </div>
  );
}
