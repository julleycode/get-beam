"use client";

import { useState } from "react";
import { ChatControls, ObButton } from "@/components/onboarding/chat-controls";

/**
 * Must match `FEEDBACK_REASONS` in apps/api/models/identity_feedback.py — the
 * server drops unknown reasons silently so the counts stay analysable.
 *
 * Rewritten from the legacy set (wrong name / wrong company / wrong socials),
 * which described a profile card that no longer exists at this beat. These four
 * describe what is actually on screen: a pin, a network, and a page list.
 */
export const FEEDBACK_REASONS = [
  { value: "wrong_city", label: "wrong city" },
  { value: "wrong_network", label: "wrong network / ISP" },
  { value: "vpn_or_proxy", label: "i'm on a VPN or proxy" },
  { value: "not_me", label: "that's not me at all" },
] as const;

export const NOTE_MAX_CHARS = 500;

export interface FeedbackPayload {
  reasons: string[];
  note: string;
}

export function IdentityFeedbackForm({
  onSubmit,
}: {
  /** Fire-and-forget: the parent advances immediately and swallows failures. */
  onSubmit: (payload: FeedbackPayload) => void;
}) {
  const [reasons, setReasons] = useState<string[]>([]);
  const [note, setNote] = useState("");

  const toggle = (value: string) =>
    setReasons((prev) =>
      prev.includes(value) ? prev.filter((r) => r !== value) : [...prev, value],
    );

  return (
    <ChatControls wide>
      {/* Native checkboxes styled with the existing .ob-check CSS. There is no
          shadcn checkbox in this repo and adding one (plus its Radix dep) for
          four boxes is the wrong trade. */}
      <div className="ob-checks" data-testid="identity-feedback-form">
        {FEEDBACK_REASONS.map((r) => {
          const on = reasons.includes(r.value);
          return (
            <label key={r.value} className={on ? "ob-check on" : "ob-check"}>
              <input
                type="checkbox"
                value={r.value}
                checked={on}
                onChange={() => toggle(r.value)}
              />
              <span>{r.label}</span>
            </label>
          );
        })}
      </div>

      <textarea
        className="ob-textarea"
        placeholder="anything else? (optional)"
        maxLength={NOTE_MAX_CHARS}
        value={note}
        onChange={(e) => setNote(e.target.value.slice(0, NOTE_MAX_CHARS))}
        aria-label="Additional feedback"
      />

      <ObButton
        variant="primary"
        onClick={() => onSubmit({ reasons, note: note.trim() })}
      >
        send it
      </ObButton>
    </ChatControls>
  );
}
