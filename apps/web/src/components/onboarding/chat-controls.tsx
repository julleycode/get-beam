"use client";

import type { ReactNode } from "react";

/**
 * The interactive row that follows a step's bot lines — buttons, a field, or
 * an embedded card. Lives on the user's (right) side, matching the static
 * funnel's `.ob-msg.controls` layout.
 *
 * `wide` opts out of the 420px cap for things that need the full column
 * (the pixel-install guide, the reveal card).
 */
export function ChatControls({
  children,
  wide = false,
}: {
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <div className={wide ? "ob-msg controls wide" : "ob-msg controls"}>
      <div className="ob-actionwrap">{children}</div>
    </div>
  );
}

export function ObButton({
  children,
  onClick,
  variant = "primary",
  type = "button",
  disabled,
  size,
  block,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "ghost";
  type?: "button" | "submit";
  disabled?: boolean;
  size?: "lg";
  block?: boolean;
}) {
  const classes = [
    "ob-btn",
    variant === "primary" ? "ob-btn-primary" : "ob-btn-ghost",
    size === "lg" ? "ob-btn-lg" : "",
    block ? "ob-btn-block" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button type={type} className={classes} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  );
}
