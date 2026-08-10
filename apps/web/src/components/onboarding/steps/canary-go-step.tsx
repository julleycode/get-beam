"use client";

import { ChatControls, ObButton } from "@/components/onboarding/chat-controls";
import { beamFingerprint } from "@/lib/beam-fingerprint";

/**
 * `?beam=canary`, NOT the legacy static funnel's `?beam=demo` — onboarding
 * traffic stays separable in the events table.
 */
export const CANARY_URL = "https://getbeam.fyi/?beam=canary";

export function CanaryGoStep({
  onStart,
  onSkip,
}: {
  /** Receives the fp2 hash computed synchronously on the click. */
  onStart: (fingerprint: string) => void;
  onSkip: () => void;
}) {
  const handleGo = () => {
    // COMPUTE THE FINGERPRINT HERE, ON THE CLICK — not lazily inside the poll.
    // Once the new tab takes focus this one is backgrounded, and a backgrounded
    // tab can perturb the canvas probe, producing a hash that does not match
    // what the pixel stored on getbeam.fyi. The join would then silently miss
    // with no error anywhere.
    let fp = "";
    try {
      fp = beamFingerprint();
    } catch {
      // No canvas/WebGL (hardened browser). The catch will not land; the
      // listen step degrades honestly rather than pretending.
      fp = "";
    }

    // noopener: the opened tab must not get a handle on this window.
    window.open(CANARY_URL, "_blank", "noopener,noreferrer");
    onStart(fp);
  };

  return (
    <ChatControls>
      <ObButton variant="primary" size="lg" onClick={handleGo}>
        catch me <span aria-hidden="true">→</span>
      </ObButton>
      <button type="button" className="ob-skip" onClick={onSkip}>
        skip, i&apos;ll just install
      </button>
    </ChatControls>
  );
}
