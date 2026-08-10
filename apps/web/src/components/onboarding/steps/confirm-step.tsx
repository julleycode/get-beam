"use client";

import { useState } from "react";
import { ChatControls, ObButton } from "@/components/onboarding/chat-controls";
import {
  IdentityFeedbackForm,
  type FeedbackPayload,
} from "@/components/onboarding/identity-feedback-form";

/**
 * "is this you?" → yes, or a form that ACTUALLY POSTS.
 *
 * The legacy funnel built these controls and then threw the answer away: its
 * submit handler was `() => ob.answer('sent you some feedback','walk')` and the
 * DOM was read zero times (onboarding-steps.js:512-521). This is the identity
 * waterfall's first precision signal, so it goes to the server.
 */
export function ConfirmStep({
  onYes,
  onFeedback,
}: {
  onYes: () => void;
  onFeedback: (payload: FeedbackPayload) => void;
}) {
  const [showForm, setShowForm] = useState(false);

  if (showForm) {
    return <IdentityFeedbackForm onSubmit={onFeedback} />;
  }

  return (
    <ChatControls>
      <ObButton variant="primary" onClick={onYes}>
        <span aria-hidden="true">✓</span> yes, that&apos;s me
      </ObButton>
      <ObButton variant="ghost" onClick={() => setShowForm(true)}>
        not quite
      </ObButton>
    </ChatControls>
  );
}
