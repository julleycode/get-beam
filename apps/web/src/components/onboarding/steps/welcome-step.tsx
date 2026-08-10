"use client";

import { ChatControls, ObButton } from "@/components/onboarding/chat-controls";

/**
 * The scripted hello. Copy lives in SCRIPT.welcome (onboarding-script.ts) —
 * folded in from the deleted onboarding-welcome-chat.tsx, which was the third
 * copy of this same conversation.
 *
 * PHASE 2: "let's do it" advances straight to `site`. The reducer's
 * `nextStep()` handles that — with CANARY_ENABLED false, welcome → site.
 * When the canary ships, flipping that constant sends this same button to
 * `canary_go` with no change here.
 */
export function WelcomeStep({
  onAdvance,
  onExit,
}: {
  onAdvance: () => void;
  onExit: () => void;
}) {
  return (
    <ChatControls>
      <ObButton variant="primary" size="lg" onClick={onAdvance}>
        let&apos;s do it <span aria-hidden="true">→</span>
      </ObButton>
      <button type="button" className="ob-skip" onClick={onExit}>
        skip for now
      </button>
    </ChatControls>
  );
}
