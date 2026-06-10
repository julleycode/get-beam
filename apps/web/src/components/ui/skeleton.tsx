import { cn } from "@/lib/utils";

/**
 * Skeleton placeholder block. Shimmer animation + sizing come from the
 * `.skeleton` class in globals.css; pass width/height via className.
 */
function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cn("skeleton rounded-md", className)}
      {...props}
    />
  );
}

export { Skeleton };
