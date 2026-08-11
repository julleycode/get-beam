"use client";

import { useEffect, useRef } from "react";

/** Don't yank the view if the user has scrolled more than this off the bottom. */
const STICK_THRESHOLD_PX = 80;

/**
 * Keep a scroll container pinned to the bottom as content grows.
 *
 * Replaces the legacy immediate/rAF/70ms triple-pin
 * (public/beam/onboarding-app.js:35-40), which existed because content can
 * load late. A `ResizeObserver` on the inner content handles that class
 * properly — including the worst case, map tiles resolving after paint.
 *
 * Adds the thing legacy lacked: only auto-pin when the user is ALREADY within
 * ~80px of the bottom. Without this the container yanks itself out from under
 * anyone reading back or panning a map.
 */
export function useAutoScroll<
  TScroll extends HTMLElement,
  TContent extends HTMLElement,
>() {
  const scrollRef = useRef<TScroll | null>(null);
  const contentRef = useRef<TContent | null>(null);
  const stuck = useRef(true);

  useEffect(() => {
    const scroller = scrollRef.current;
    const content = contentRef.current;
    if (!scroller) return;

    const distanceFromBottom = () =>
      scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;

    const onScroll = () => {
      stuck.current = distanceFromBottom() <= STICK_THRESHOLD_PX;
    };
    scroller.addEventListener("scroll", onScroll, { passive: true });

    const pin = () => {
      if (stuck.current) scroller.scrollTop = scroller.scrollHeight;
    };
    pin();

    let observer: ResizeObserver | null = null;
    if (content && typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(pin);
      observer.observe(content);
    }

    return () => {
      scroller.removeEventListener("scroll", onScroll);
      observer?.disconnect();
    };
  }, []);

  return { scrollRef, contentRef };
}
