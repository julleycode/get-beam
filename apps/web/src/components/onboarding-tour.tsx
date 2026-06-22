"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/button";
import { BeamMascot } from "@/components/beam-mascot";
import type { TourStep } from "@/lib/tour-steps";

type OnboardingTourProps = {
  steps: TourStep[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called once when the tour is skipped or finished — persists the "seen" flag. */
  onComplete: () => void;
  isAdmin: boolean;
};

type Rect = { top: number; left: number; width: number; height: number };

const CARD_WIDTH = 320;
const CARD_EST_HEIGHT = 240;
const SPOTLIGHT_PAD = 6;
const MAX_MEASURE_TRIES = 12;

export function OnboardingTour({
  steps,
  open,
  onOpenChange,
  onComplete,
  isAdmin,
}: OnboardingTourProps) {
  const [mounted, setMounted] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);
  const [isDesktop, setIsDesktop] = useState(true);
  const cardRef = useRef<HTMLDivElement>(null);
  const lastFocused = useRef<HTMLElement | null>(null);

  // adminOnly steps are dropped for non-admins so we never spotlight a nav item
  // that isn't in their sidebar (mirrors the nav's own filtering).
  const activeSteps = useMemo(
    () => steps.filter((s) => !s.adminOnly || isAdmin),
    [steps, isAdmin]
  );

  const safeIndex = Math.min(stepIndex, Math.max(activeSteps.length - 1, 0));
  const step = activeSteps[safeIndex];
  const isFirst = safeIndex === 0;
  const isLast = safeIndex >= activeSteps.length - 1;

  useEffect(() => setMounted(true), []);

  // Mirror the `md` breakpoint — below it the sidebar is hidden behind a drawer,
  // so spotlighting it is meaningless; we fall back to a centered card.
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 768px)");
    const update = () => setIsDesktop(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  // Restart at step 0 each time the tour opens; restore focus when it closes.
  useEffect(() => {
    if (open) {
      setStepIndex(0);
      lastFocused.current = document.activeElement as HTMLElement | null;
    } else {
      lastFocused.current?.focus?.();
    }
  }, [open]);

  const finish = useCallback(() => {
    onComplete();
    onOpenChange(false);
  }, [onComplete, onOpenChange]);

  const goNext = useCallback(() => {
    if (isLast) finish();
    else setStepIndex((i) => i + 1);
  }, [isLast, finish]);

  const goBack = useCallback(() => setStepIndex((i) => Math.max(0, i - 1)), []);

  // Measure the active target and keep the spotlight glued to it on
  // scroll/resize/late layout. Retries a few frames for items that mount after
  // /auth/me; gives up to a centered card if the target never appears.
  useLayoutEffect(() => {
    if (!open) return;
    let raf = 0;
    let tries = 0;

    const measure = () => {
      if (!step || step.target === null || !isDesktop) {
        setRect(null);
        return;
      }
      const el = document.querySelector(`aside [data-tour="${step.target}"]`);
      if (el) {
        const r = el.getBoundingClientRect();
        setRect({ top: r.top, left: r.left, width: r.width, height: r.height });
      } else if (tries < MAX_MEASURE_TRIES) {
        tries += 1;
        raf = requestAnimationFrame(measure);
      } else {
        setRect(null);
      }
    };

    measure();

    const onChange = () => {
      if (raf) cancelAnimationFrame(raf);
      raf = requestAnimationFrame(measure);
    };
    window.addEventListener("resize", onChange);
    window.addEventListener("scroll", onChange, true);
    return () => {
      if (raf) cancelAnimationFrame(raf);
      window.removeEventListener("resize", onChange);
      window.removeEventListener("scroll", onChange, true);
    };
  }, [open, step, isDesktop]);

  // Move focus into the card on open / step change for keyboard users.
  useEffect(() => {
    if (open) requestAnimationFrame(() => cardRef.current?.focus());
  }, [open, safeIndex]);

  // Keyboard: Esc skips, →/Enter advance, ← goes back.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        finish();
      } else if (e.key === "ArrowRight" || e.key === "Enter") {
        e.preventDefault();
        goNext();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        goBack();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, finish, goNext, goBack]);

  const cardStyle: CSSProperties = useMemo(() => {
    if (rect && isDesktop) {
      const gap = 12;
      let left = rect.left + rect.width + gap;
      if (left + CARD_WIDTH + 16 > window.innerWidth) {
        left = Math.max(16, rect.left - CARD_WIDTH - gap);
      }
      let top = Math.min(rect.top, window.innerHeight - CARD_EST_HEIGHT - 16);
      // Keep clear of the viewport top so the mascot peeking above the card
      // isn't clipped.
      top = Math.max(60, top);
      return { position: "fixed", top, left, width: CARD_WIDTH };
    }
    return {
      position: "fixed",
      top: "50%",
      left: "50%",
      transform: "translate(-50%, -50%)",
      width: "min(90vw, 360px)",
    };
  }, [rect, isDesktop]);

  if (!open || !mounted || !step) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[60]"
      role="dialog"
      aria-modal="true"
      aria-labelledby="tour-title"
    >
      {/* Dim: a spotlight cutout when a target is measured, else a flat backdrop.
          The container itself captures clicks, so the page underneath is inert. */}
      {rect ? (
        <div
          className="pointer-events-none absolute rounded-md transition-all duration-200"
          style={{
            top: rect.top - SPOTLIGHT_PAD,
            left: rect.left - SPOTLIGHT_PAD,
            width: rect.width + SPOTLIGHT_PAD * 2,
            height: rect.height + SPOTLIGHT_PAD * 2,
            boxShadow:
              "0 0 0 9999px hsl(var(--foreground) / 0.6), 0 0 0 2px hsl(var(--primary) / 0.9)",
          }}
        />
      ) : (
        <div className="absolute inset-0 bg-foreground/60" />
      )}

      <div
        ref={cardRef}
        tabIndex={-1}
        style={cardStyle}
        className="pointer-events-auto relative rounded-lg border bg-card px-5 pb-5 pt-6 shadow-lg outline-none animate-in fade-in zoom-in-95"
      >
        <BeamMascot className="pointer-events-none absolute -top-12 left-4 h-16 w-auto drop-shadow-md" />
        <p className="text-xs text-muted-foreground">
          Step {safeIndex + 1} of {activeSteps.length}
        </p>
        <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-primary transition-all duration-200"
            style={{ width: `${((safeIndex + 1) / activeSteps.length) * 100}%` }}
          />
        </div>
        <h2
          id="tour-title"
          className="mt-3 font-serif text-lg font-semibold tracking-tight"
        >
          {step.title}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">{step.body}</p>
        <div className="mt-4 flex items-center justify-between gap-2">
          <Button variant="ghost" size="sm" onClick={finish}>
            Skip
          </Button>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={goBack} disabled={isFirst}>
              Back
            </Button>
            <Button size="sm" onClick={goNext}>
              {isLast ? "Finish" : "Next"}
            </Button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}
