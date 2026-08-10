"use client";

import { useEffect, useRef, useState } from "react";
import { typingDelay } from "@/lib/onboarding-flow";
import type { Line } from "@/lib/onboarding-script";

export interface MessageQueue {
  /** Lines revealed so far. */
  visible: Line[];
  /** True while the typing dots should show for the next line. */
  typing: boolean;
  /** True once every line for this key has revealed. */
  done: boolean;
}

/**
 * Reveal a step's lines one at a time, with a typing pause between them.
 *
 * ONE effect, keyed on `key`, with a `cancelled` flag and a cleared timeout
 * ref. Because rendering is state-driven, React 18 StrictMode's
 * mount → cleanup → mount can simply replay it — which is why the
 * `chatRef.innerHTML = ""` hack in the deleted onboarding-welcome-chat.tsx
 * (line 118) is gone rather than ported.
 *
 * `reduced` collapses every delay to 0, so reduced-motion users (and the
 * Playwright reduced-motion leg) get the whole step at once.
 */
export function useMessageQueue(
  lines: Line[],
  key: string,
  reduced: boolean,
): MessageQueue {
  const [count, setCount] = useState(0);
  const [typing, setTyping] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // `lines` is rebuilt on every render by linesFor(); depending on it directly
  // would restart the queue forever. The step key is the real identity.
  const linesRef = useRef(lines);
  linesRef.current = lines;

  useEffect(() => {
    let cancelled = false;
    setCount(0);
    setTyping(false);

    const run = async () => {
      const queue = linesRef.current;
      for (let i = 0; i < queue.length; i++) {
        if (cancelled) return;
        const line = queue[i];
        const delay = line.delay ?? typingDelay(line.text, reduced);
        const wait = reduced ? 0 : delay;

        if (wait > 0) {
          setTyping(true);
          await new Promise<void>((resolve) => {
            timer.current = setTimeout(resolve, wait);
          });
          if (cancelled) return;
        }
        setTyping(false);
        setCount(i + 1);

        if (!reduced) {
          await new Promise<void>((resolve) => {
            timer.current = setTimeout(resolve, 160);
          });
          if (cancelled) return;
        }
      }
    };

    void run();

    return () => {
      cancelled = true;
      if (timer.current) clearTimeout(timer.current);
      timer.current = null;
    };
  }, [key, reduced]);

  return {
    visible: lines.slice(0, count),
    typing,
    done: count >= lines.length,
  };
}
