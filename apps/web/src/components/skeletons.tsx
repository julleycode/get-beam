/**
 * Composable skeleton blocks for page loading states.
 *
 * Every block mirrors the real loaded layout's structure and heights so the
 * skeleton→content swap causes no layout shift (CLS). Built on the same
 * ui/card and ui/table primitives the real pages use, so paddings, borders,
 * and column rhythm match exactly.
 */

import { BeamLogo } from "@/components/beam-logo";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

/** h2 title bar + optional right-side control (e.g. site selector). */
export function PageHeaderSkeleton({ control = false }: { control?: boolean }) {
  return (
    <div className="mb-6 flex items-center justify-between">
      <Skeleton className="h-8 w-44" />
      {control && <Skeleton className="h-9 w-[200px]" />}
    </div>
  );
}

/** Stat blocks row (big number + small label per column). */
export function StatGridSkeleton({ cols = 3 }: { cols?: number }) {
  return (
    <div
      className="grid gap-2 text-center"
      style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
    >
      {Array.from({ length: cols }).map((_, i) => (
        <div key={i} className="flex flex-col items-center gap-1.5 py-1">
          <Skeleton className="h-8 w-16" />
          <Skeleton className="h-3 w-20" />
        </div>
      ))}
    </div>
  );
}

// Varied bar widths so table rows don't look like a flat grid.
const CELL_WIDTHS = ["w-24", "w-16", "w-28", "w-12", "w-20", "w-14", "w-24"];

/** Real <Table> shell with skeleton header + rows; column rhythm matches. */
export function TableSkeleton({
  cols,
  rows = 8,
}: {
  cols: number;
  rows?: number;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          {Array.from({ length: cols }).map((_, c) => (
            <TableHead key={c}>
              <Skeleton className="h-4 w-16" />
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {Array.from({ length: rows }).map((_, r) => (
          <TableRow key={r}>
            {Array.from({ length: cols }).map((_, c) => (
              <TableCell key={c}>
                <Skeleton
                  className={`h-4 ${CELL_WIDTHS[(r + c) % CELL_WIDTHS.length]}`}
                />
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** Grid of generic card shells (title, two lines, chip row). */
export function CardGridSkeleton({
  cards = 4,
  cols = 2,
}: {
  cards?: number;
  cols?: number;
}) {
  return (
    <div
      className="grid gap-4"
      style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
    >
      {Array.from({ length: cards }).map((_, i) => (
        <Card key={i}>
          <CardHeader>
            <Skeleton className="h-5 w-36" />
          </CardHeader>
          <CardContent className="space-y-3">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-3/4" />
            <div className="flex gap-2 pt-1">
              <Skeleton className="h-6 w-16 rounded-full" />
              <Skeleton className="h-6 w-20 rounded-full" />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

/** Stacked list cards (feed/drafts/board): optional leading square + lines. */
export function ListCardSkeleton({
  rows = 4,
  leading = false,
}: {
  rows?: number;
  leading?: boolean;
}) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <Card key={i}>
          <CardContent className="flex items-start gap-4 pb-4 pt-4">
            {leading && <Skeleton className="h-14 w-12 shrink-0 rounded-xl" />}
            <div className="min-w-0 flex-1 space-y-2">
              <Skeleton className="h-5 w-2/5" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/5" />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

/** Mirrors the dashboard SiteCard: title, url, stats, pixel row, buttons. */
export function SiteCardSkeleton() {
  return (
    <Card>
      <CardHeader className="space-y-2">
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-4 w-48" />
      </CardHeader>
      <CardContent className="space-y-4">
        <StatGridSkeleton cols={3} />
        <Skeleton className="h-4 w-36" />
        <div className="flex gap-2">
          <Skeleton className="h-8 w-20 rounded-md" />
          <Skeleton className="h-8 w-20 rounded-md" />
          <Skeleton className="h-8 w-24 rounded-md" />
        </div>
      </CardContent>
    </Card>
  );
}

/** Card with label + input-height bars (settings-style forms). */
export function FormCardSkeleton({ fields = 3 }: { fields?: number }) {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-5 w-40" />
      </CardHeader>
      <CardContent className="space-y-4">
        {Array.from({ length: fields }).map((_, i) => (
          <div key={i} className="space-y-1.5">
            <Skeleton className="h-3.5 w-24" />
            <Skeleton className="h-9 w-full" />
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

/** Placeholder matching the SiteSelector trigger while sites load. */
export function SelectSkeleton() {
  return <Skeleton className="h-9 w-[200px]" />;
}

/** Fullscreen branded splash for auth-resolution moments ("/", invite gate). */
export function BrandSplash() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="animate-pulse">
        <BeamLogo className="w-14" />
      </div>
    </div>
  );
}
