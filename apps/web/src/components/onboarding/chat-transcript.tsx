"use client";

import { BeamMascot } from "@/components/beam-mascot";
import type { Line } from "@/lib/onboarding-script";

/**
 * Bot/user bubbles + typing dots.
 *
 * Every line is rendered as a TEXT NODE. No `innerHTML`, no
 * `dangerouslySetInnerHTML` — the legacy funnel interpolated
 * provider-supplied names into bubble markup, which is the XSS shape this
 * rewrite removes structurally.
 */

export function BotBubble({ line }: { line: Line }) {
  return (
    <div className="ob-msg bot">
      <div className="ob-av">
        <BeamMascot className="beam-mascot-svg" palette="chat" />
      </div>
      <div className="ob-bubble reveal">
        <p className={line.lead ? "lead" : line.muted ? "muted" : undefined}>
          {line.text}
        </p>
      </div>
    </div>
  );
}

export function TypingBubble() {
  return (
    <div className="ob-msg bot" aria-hidden="true">
      <div className="ob-av">
        <BeamMascot className="beam-mascot-svg" palette="chat" />
      </div>
      <div className="ob-bubble typing">
        <span className="dots">
          <span />
          <span />
          <span />
        </span>
      </div>
    </div>
  );
}

export function UserBubble({ text }: { text: string }) {
  return (
    <div className="ob-msg user">
      <div className="ob-bubble reveal">{text}</div>
    </div>
  );
}

export function ChatTranscript({
  lines,
  typing,
}: {
  lines: Line[];
  typing: boolean;
}) {
  return (
    <>
      {lines.map((line, i) => (
        <BotBubble key={`${i}-${line.text}`} line={line} />
      ))}
      {typing && <TypingBubble />}
    </>
  );
}
