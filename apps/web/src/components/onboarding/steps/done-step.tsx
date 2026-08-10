"use client";

import { ChatControls, ObButton } from "@/components/onboarding/chat-controls";

export function DoneStep({ onFinish }: { onFinish: () => void }) {
  return (
    <ChatControls>
      <ObButton variant="primary" size="lg" onClick={onFinish}>
        open the dashboard <span aria-hidden="true">→</span>
      </ObButton>
    </ChatControls>
  );
}
