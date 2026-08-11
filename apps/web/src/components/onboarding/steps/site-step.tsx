"use client";

import { useState } from "react";
import { ChatControls, ObButton } from "@/components/onboarding/chat-controls";

/**
 * Site creation, inside the chat.
 *
 * Wired to the REAL `api.createSite` / `api.getPixelSnippet` /
 * `api.detectPlatform` via the parent's `onSubmit` — nothing here is scripted
 * or faked. The legacy static funnel shipped a hard-coded
 * `data-site="YOUR_SITE_ID"` snippet and a `setTimeout(advance, 3600)` fake
 * detection; both are structurally impossible on this path because the
 * snippet only ever arrives from the API response.
 */
export function SiteStep({
  onSubmit,
  submitting,
  error,
  showUpgrade,
}: {
  onSubmit: (values: { name: string; url: string; description: string }) => void;
  submitting: boolean;
  error: string | null;
  showUpgrade: boolean;
}) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");

  return (
    <ChatControls>
      <form
        className="ob-actionwrap"
        style={{ width: "100%" }}
        onSubmit={(e) => {
          e.preventDefault();
          if (submitting) return;
          onSubmit({ name: name.trim(), url: url.trim(), description: description.trim() });
        }}
      >
        <div>
          <label className="ob-label" htmlFor="ob-site-url">
            site url
          </label>
          <input
            id="ob-site-url"
            className="ob-input-plain"
            type="url"
            required
            value={url}
            placeholder="https://mystore.com"
            onChange={(e) => setUrl(e.target.value)}
          />
        </div>

        <div>
          <label className="ob-label" htmlFor="ob-site-name">
            name it
          </label>
          <input
            id="ob-site-name"
            className="ob-input-plain"
            type="text"
            required
            value={name}
            placeholder="My Store"
            onChange={(e) => setName(e.target.value)}
          />
        </div>

        <div>
          <label className="ob-label" htmlFor="ob-site-desc">
            what do you sell? (optional — sharpens the ai drafts)
          </label>
          <textarea
            id="ob-site-desc"
            className="ob-textarea"
            rows={2}
            value={description}
            placeholder="handmade candles for wellness enthusiasts…"
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>

        {error && (
          <p className="ob-error">
            {error}
            {showUpgrade && (
              <>
                {" "}
                <a href="/pricing">view plans</a>
              </>
            )}
          </p>
        )}

        <ObButton type="submit" variant="primary" disabled={submitting}>
          {submitting ? "creating…" : "continue →"}
        </ObButton>
      </form>
    </ChatControls>
  );
}
