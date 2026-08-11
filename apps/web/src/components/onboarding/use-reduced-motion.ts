"use client";

import { useEffect, useState } from "react";

/**
 * `prefers-reduced-motion: reduce`, kept live.
 *
 * Starts `false` so SSR and the first client render agree (no hydration
 * mismatch), then corrects in an effect. Playwright's
 * `emulateMedia({ reducedMotion: "reduce" })` flips this and the whole chat
 * reveals immediately, which is how the e2e legs stay fast and deterministic.
 */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);

    const onChange = (e: MediaQueryListEvent) => setReduced(e.matches);
    // Safari < 14 only has the deprecated addListener.
    if (typeof mq.addEventListener === "function") {
      mq.addEventListener("change", onChange);
      return () => mq.removeEventListener("change", onChange);
    }
    mq.addListener(onChange);
    return () => mq.removeListener(onChange);
  }, []);

  return reduced;
}
