import { forwardRef } from "react";

import { Button, type ButtonProps } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface IconButtonProps extends Omit<ButtonProps, "size" | "variant"> {
  /** Required — used as both the accessible name and the hover tooltip,
   * since the button has no visible text. */
  label: string;
  /** Red-on-hover for destructive actions (delete, disconnect). */
  danger?: boolean;
}

/**
 * Square ghost icon button for row/card-level secondary and destructive
 * actions (delete, archive, disconnect…). One source of truth so every
 * table and card action looks identical across the app. Pass a single
 * lucide icon as the child; keep primary CTAs as normal text `<Button>`s.
 */
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  ({ label, danger, className, children, ...props }, ref) => (
    <Button
      ref={ref}
      type="button"
      variant="ghost"
      size="sm"
      className={cn(
        "h-7 w-7 shrink-0 p-0 text-muted-foreground",
        danger ? "hover:text-destructive" : "hover:text-foreground",
        className
      )}
      aria-label={label}
      title={label}
      {...props}
    >
      {children}
    </Button>
  )
);
IconButton.displayName = "IconButton";
