import { Card, CardContent } from "@/components/ui/card";

interface EmptyStateProps {
  title: string;
  description: React.ReactNode;
  icon?: React.ReactNode;
  action?: React.ReactNode;
  progress?: { current: number; target: number; label: string };
}

/** Shared empty state: explains WHY a page is empty and WHEN it fills. */
export function EmptyState({ title, description, icon, action, progress }: EmptyStateProps) {
  const pct = progress
    ? Math.min(100, Math.round((progress.current / progress.target) * 100))
    : 0;

  return (
    <Card>
      <CardContent className="flex flex-col items-center p-8 text-center">
        {icon && <div className="mb-3 text-muted-foreground">{icon}</div>}
        <h3 className="text-base font-semibold">{title}</h3>
        <p className="mt-2 max-w-md text-sm text-muted-foreground">{description}</p>

        {progress && (
          <div className="mt-4 w-full max-w-xs">
            <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-2 rounded-full bg-primary transition-all"
                style={{ width: `${pct}%` }}
              />
            </div>
            <p className="mt-1.5 text-xs text-muted-foreground">
              {Math.min(progress.current, progress.target)} of {progress.target} {progress.label}
            </p>
          </div>
        )}

        {action && <div className="mt-4">{action}</div>}
      </CardContent>
    </Card>
  );
}
