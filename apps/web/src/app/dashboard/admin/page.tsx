"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import { api } from "@/lib/api";
import { ADMIN_TOOLS } from "@/lib/admin-nav";
import { Card, CardContent } from "@/components/ui/card";

/** Admin hub — one place that gathers every admin-only tool. Each card links
 *  out to the tool's own route. Non-admins who reach the URL directly see a
 *  notice (the pages themselves are backend-gated regardless). */
export default function AdminPage() {
  const { data: me } = useQuery({
    queryKey: ["me"],
    queryFn: () => api.getMe(),
    staleTime: 5 * 60_000,
  });

  if (me && me.is_admin !== true) {
    return (
      <div className="flex flex-col items-center gap-2 py-16 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-warning-muted text-warning">
          <ShieldAlert className="h-6 w-6" />
        </div>
        <p className="font-serif text-base font-semibold">Admins only</p>
        <p className="text-sm text-muted-foreground">
          You don&apos;t have access to this area.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-serif text-2xl font-semibold tracking-tight">Admin</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Internal tools and management.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {ADMIN_TOOLS.map((tool) => (
          <Link key={tool.href} href={tool.href}>
            <Card className="h-full transition-colors hover:bg-secondary/50">
              <CardContent className="flex items-start gap-3 p-4">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-secondary text-primary">
                  <tool.icon className="h-5 w-5" />
                </span>
                <div>
                  <p className="text-sm font-medium">{tool.label}</p>
                  <p className="text-xs text-muted-foreground">{tool.description}</p>
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
