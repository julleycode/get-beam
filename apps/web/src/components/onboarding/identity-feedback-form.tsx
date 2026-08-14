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
/** Must match `ACTUAL_CITY_MAX_CHARS` in apps/api/models/identity_feedback.py. */
export const ACTUAL_CITY_MAX_CHARS = 120;

export interface FeedbackPayload {
  reasons: string[];
  note: string;
  /**
   * The city the user says they are ACTUALLY in. Only collected — and only
   * stored server-side — alongside `wrong_city`.
   *
   * This is the ground truth half of the loop: `wrong_city` on its own says the
   * reveal was wrong, this says what right would have been, which is the only
   * way to grade one geo provider against another without paying for a third.
   */
  actualCity: string;
}

export function IdentityFeedbackForm({
  onSubmit,
}: {
  /** Fire-and-forget: the parent advances immediately and swallows failures. */
  onSubmit: (payload: FeedbackPayload) => void;
}) {
  const [reasons, setReasons] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [actualCity, setActualCity] = useState("");

  const toggle = (value: string) =>
    setReasons((prev) =>
      prev.includes(value) ? prev.filter((r) => r !== value) : [...prev, value],
    );

  const wrongCity = reasons.includes("wrong_city");

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

      {/* Revealed only by "wrong city", never asked up front: an unprompted
          "where are you?" is a location request, while this one is the user
          correcting a claim Beam just made about them. Same words, opposite
          feeling. Optional — sending the reason with no city is still useful.

          ob-input-plain, not ob-input: the latter is the borderless inner field
          of an .ob-field group and renders as naked text on its own. */}
      {wrongCity && (
        <input
          type="text"
          className="ob-input-plain"
          placeholder="so where are you actually? (optional)"
          maxLength={ACTUAL_CITY_MAX_CHARS}
          value={actualCity}
          onChange={(e) =>
            setActualCity(e.target.value.slice(0, ACTUAL_CITY_MAX_CHARS))
          }
          aria-label="The city you are actually in"
          data-testid="identity-feedback-actual-city"
          autoComplete="off"
        />
      )}

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
        onClick={() =>
          onSubmit({
            reasons,
            note: note.trim(),
            // Cleared when the box is not showing, so unticking "wrong city"
            // after typing cannot smuggle a stale value through.
            actualCity: wrongCity ? actualCity.trim() : "",
          })
        }
      >
        send it
      </ObButton>
    </ChatControls>
  );
}
