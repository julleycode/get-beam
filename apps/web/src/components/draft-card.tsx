"use client";

import { useState } from "react";
import type { SocialDraft as Draft } from "@/lib/api";
import { PlatformBadge } from "./platform-badge";

interface DraftCardProps {
  draft: Draft;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onEdit: (id: string, content: string) => void;
  loading?: boolean;
}

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-yellow-50 text-yellow-700",
  approved: "bg-blue-50 text-blue-700",
  sent: "bg-green-50 text-green-700",
  rejected: "bg-gray-50 text-gray-500",
  failed: "bg-red-50 text-red-700",
};

export function DraftCard({
  draft,
  onApprove,
  onReject,
  onEdit,
  loading,
}: DraftCardProps) {
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(
    draft.edited_content || draft.ai_content
  );

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4 space-y-3">
      {/* Original context */}
      {draft.original_content && (
        <div className="bg-gray-50 rounded-md p-3 space-y-1">
          <p className="text-xs text-gray-400">
            Replying to @{draft.original_author}
          </p>
          <p className="text-sm text-gray-600">{draft.original_content}</p>
        </div>
      )}

      {/* Draft content */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <PlatformBadge platform={draft.platform} />
          <span
            className={`text-xs px-2 py-0.5 rounded font-medium ${STATUS_STYLES[draft.status]}`}
          >
            {draft.status}
          </span>
          {draft.strategy_label && (
            <span
              className={`text-xs px-2 py-0.5 rounded font-medium ${
                draft.strategy === "direct"
                  ? "bg-blue-50 text-blue-600"
                  : draft.strategy === "conversational"
                    ? "bg-green-50 text-green-600"
                    : "bg-purple-50 text-purple-600"
              }`}
            >
              {draft.strategy_label}
            </span>
          )}
        </div>

        {editing ? (
          <textarea
            value={editText}
            onChange={(e) => setEditText(e.target.value)}
            className="w-full border border-gray-300 rounded-md p-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            rows={3}
          />
        ) : (
          <p className="text-sm text-gray-800 leading-relaxed">
            {draft.edited_content || draft.ai_content}
          </p>
        )}
      </div>

      {/* Actions */}
      {draft.status === "pending" && (
        <div className="flex items-center gap-2 pt-1">
          {editing ? (
            <>
              <button
                onClick={() => {
                  onEdit(draft.id, editText);
                  setEditing(false);
                }}
                className="text-xs px-3 py-1.5 rounded-md bg-indigo-600 text-white hover:bg-indigo-700"
              >
                Save
              </button>
              <button
                onClick={() => setEditing(false)}
                className="text-xs px-3 py-1.5 rounded-md border border-gray-300 text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => onApprove(draft.id)}
                disabled={loading}
                className="text-xs px-3 py-1.5 rounded-md bg-green-600 text-white hover:bg-green-700 disabled:opacity-50"
              >
                {loading ? "Sending..." : "Approve & Send"}
              </button>
              <button
                onClick={() => setEditing(true)}
                className="text-xs px-3 py-1.5 rounded-md border border-gray-300 text-gray-600 hover:bg-gray-50"
              >
                Edit
              </button>
              <button
                onClick={() => onReject(draft.id)}
                disabled={loading}
                className="text-xs px-3 py-1.5 rounded-md border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-50"
              >
                Reject
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
