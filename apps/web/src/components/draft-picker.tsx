"use client";

import { useState } from "react";
import type { SocialDraft as Draft, GenerateMultiDraftResponse } from "@/lib/api";
import { PlatformBadge } from "./platform-badge";

interface DraftPickerProps {
  data: GenerateMultiDraftResponse;
  onApprove: (draftId: string) => void;
  onReject: (draftId: string) => void;
  onEdit: (draftId: string, content: string) => void;
  onDismiss: () => void;
  loading?: boolean;
}

const STRATEGY_ICONS: Record<string, string> = {
  direct: "D",
  conversational: "C",
  thought_provoking: "T",
};

const STRATEGY_COLORS: Record<string, string> = {
  direct: "border-blue-300 bg-blue-50",
  conversational: "border-green-300 bg-green-50",
  thought_provoking: "border-purple-300 bg-purple-50",
};

export function DraftPicker({
  data,
  onApprove,
  onReject,
  onEdit,
  onDismiss,
  loading,
}: DraftPickerProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { mode, drafts, voice_example_count } = data;

  const handleStartEdit = (draft: Draft) => {
    setEditingId(draft.id);
    setEditText(draft.edited_content || draft.ai_content);
  };

  const handleSaveEdit = (draftId: string) => {
    onEdit(draftId, editText);
    setEditingId(null);
  };

  const handleApprove = (draftId: string) => {
    setSelectedId(draftId);
    onApprove(draftId);
  };

  if (drafts.length === 0) return null;

  // Single draft (confident mode) — simplified view
  if (drafts.length === 1) {
    const draft = drafts[0];
    return (
      <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <PlatformBadge platform={draft.platform} />
            {draft.strategy_label && (
              <span className="text-xs text-indigo-600 font-medium">
                {draft.strategy_label}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-400">
              GBrain: {voice_example_count} examples
            </span>
            <button
              onClick={onDismiss}
              className="text-xs text-gray-400 hover:text-gray-600"
            >
              ✕
            </button>
          </div>
        </div>

        {editingId === draft.id ? (
          <div className="space-y-2">
            <textarea
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              className="w-full border border-gray-300 rounded-md p-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              rows={3}
            />
            <div className="flex gap-2">
              <button
                onClick={() => handleSaveEdit(draft.id)}
                className="text-xs px-3 py-1.5 rounded-md bg-indigo-600 text-white hover:bg-indigo-700"
              >
                Save
              </button>
              <button
                onClick={() => setEditingId(null)}
                className="text-xs px-3 py-1.5 rounded-md border border-gray-300 text-gray-600"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <>
            <p className="text-sm text-gray-800 leading-relaxed">
              {draft.edited_content || draft.ai_content}
            </p>
            <div className="flex items-center gap-2">
              <button
                onClick={() => handleApprove(draft.id)}
                disabled={loading}
                className="text-xs px-3 py-1.5 rounded-md bg-green-600 text-white hover:bg-green-700 disabled:opacity-50"
              >
                {loading && selectedId === draft.id
                  ? "Sending..."
                  : "Approve & Send"}
              </button>
              <button
                onClick={() => handleStartEdit(draft)}
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
            </div>
          </>
        )}
      </div>
    );
  }

  // Multi-draft (learning mode) — card selection view
  return (
    <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-indigo-900">
            Pick your favorite reply
          </span>
          <span className="text-xs text-indigo-500 bg-indigo-100 px-2 py-0.5 rounded-full">
            {mode === "learning"
              ? `Learning (${voice_example_count}/5 examples)`
              : "Checking preference"}
          </span>
        </div>
        <button
          onClick={onDismiss}
          className="text-xs text-gray-400 hover:text-gray-600"
        >
          ✕
        </button>
      </div>

      <div className="grid gap-2">
        {drafts.map((draft) => {
          const strategyColor =
            STRATEGY_COLORS[draft.strategy || ""] || "border-gray-300 bg-white";
          const isEditing = editingId === draft.id;

          return (
            <div
              key={draft.id}
              className={`rounded-lg border-2 p-3 transition-all ${strategyColor} ${
                selectedId === draft.id ? "ring-2 ring-indigo-500" : ""
              }`}
            >
              <div className="flex items-center gap-2 mb-2">
                <span
                  className={`w-5 h-5 flex items-center justify-center rounded text-xs font-bold text-white ${
                    draft.strategy === "direct"
                      ? "bg-blue-500"
                      : draft.strategy === "conversational"
                        ? "bg-green-500"
                        : "bg-purple-500"
                  }`}
                >
                  {STRATEGY_ICONS[draft.strategy || ""] || "?"}
                </span>
                <span className="text-xs font-medium text-gray-700">
                  {draft.strategy_label || draft.strategy}
                </span>
              </div>

              {isEditing ? (
                <div className="space-y-2">
                  <textarea
                    value={editText}
                    onChange={(e) => setEditText(e.target.value)}
                    className="w-full border border-gray-300 rounded-md p-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    rows={2}
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleSaveEdit(draft.id)}
                      className="text-xs px-3 py-1.5 rounded-md bg-indigo-600 text-white hover:bg-indigo-700"
                    >
                      Save
                    </button>
                    <button
                      onClick={() => setEditingId(null)}
                      className="text-xs px-3 py-1.5 rounded-md border border-gray-300 text-gray-600"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <p className="text-sm text-gray-800 leading-relaxed mb-2">
                    {draft.edited_content || draft.ai_content}
                  </p>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handleApprove(draft.id)}
                      disabled={loading}
                      className="text-xs px-3 py-1.5 rounded-md bg-green-600 text-white hover:bg-green-700 disabled:opacity-50"
                    >
                      {loading && selectedId === draft.id
                        ? "Sending..."
                        : "Pick This"}
                    </button>
                    <button
                      onClick={() => handleStartEdit(draft)}
                      className="text-xs px-2 py-1.5 rounded-md text-gray-500 hover:bg-white/50"
                    >
                      Edit
                    </button>
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>

      <div className="flex justify-end">
        <button
          onClick={() => drafts.forEach((d) => onReject(d.id))}
          disabled={loading}
          className="text-xs px-3 py-1.5 rounded-md border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-50"
        >
          Reject All — Write My Own
        </button>
      </div>
    </div>
  );
}
