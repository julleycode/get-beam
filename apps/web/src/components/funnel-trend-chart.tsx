"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TimeseriesPoint } from "@/lib/api";

// "YYYY-MM-DD" → "M/D" for compact axis ticks.
const fmtDay = (d: string) => {
  const [, m, day] = d.split("-");
  return `${Number(m)}/${Number(day)}`;
};

const SERIES = [
  { key: "visitors", name: "Visitors", color: "hsl(var(--muted-foreground))" },
  { key: "identified", name: "Identified", color: "hsl(var(--info))" },
  { key: "high_intent", name: "High-intent", color: "hsl(var(--primary))" },
] as const;

/** Per-day funnel trend (visitors / identified / high-intent) as a line chart.
 *  Colors come from theme tokens so it tracks light/dark. */
export function FunnelTrendChart({ data }: { data: TimeseriesPoint[] }) {
  return (
    <div className="w-full">
      {/* Explicit pixel height so ResponsiveContainer never reads a 0-height
          parent during hydration (would collapse / FOUC the chart). */}
      <ResponsiveContainer width="100%" height={224}>
        <LineChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="hsl(var(--border))"
            vertical={false}
          />
          <XAxis
            dataKey="date"
            tickFormatter={fmtDay}
            tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
            stroke="hsl(var(--border))"
            minTickGap={28}
          />
          <YAxis
            allowDecimals={false}
            width={28}
            tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
            stroke="hsl(var(--border))"
          />
          <Tooltip
            labelFormatter={(l) => fmtDay(String(l))}
            contentStyle={{
              background: "hsl(var(--popover))",
              border: "1px solid hsl(var(--border))",
              borderRadius: 8,
              fontSize: 12,
            }}
            labelStyle={{ color: "hsl(var(--foreground))", fontWeight: 600 }}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} iconType="plainline" />
          {SERIES.map((s) => (
            <Line
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.name}
              stroke={s.color}
              strokeWidth={2}
              dot={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
