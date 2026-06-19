"use client";

import { useState } from "react";
import type { SocialDraft as Draft } from "@/lib/api";
import { PlatformBadge } from "./platform-badge";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { StatusBadge } from "@/components/ui/status-badge";

interface DraftCardProps {
  draft: Draft;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onEdit: (id: string, content: string) => void;
  loading?: boolean;
}

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
    <Card>
      <CardContent className="space-y-3 p-4">
        {/* Original context */}
        {draft.original_content && (
          <div className="space-y-1 rounded-md bg-muted p-3">
            <p className="text-xs text-muted-foreground">
              Replying to @{draft.original_author}
            </p>
            <p className="text-sm text-muted-foreground">{draft.original_content}</p>
          </div>
        )}

        {/* Draft content */}
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <PlatformBadge platform={draft.platform} />
            <StatusBadge status={draft.status} />
            {draft.strategy_label && (
              <Badge variant="secondary">{draft.strategy_label}</Badge>
            )}
          </div>

          {editing ? (
            <Textarea
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              rows={3}
            />
          ) : (
            <p className="text-sm leading-relaxed text-foreground">
              {draft.edited_content || draft.ai_content}
            </p>
          )}
        </div>

        {/* Actions */}
        {draft.status === "pending" && (
          <div className="flex items-center gap-2 pt-1">
            {editing ? (
              <>
                <Button
                  size="sm"
                  onClick={() => {
                    onEdit(draft.id, editText);
                    setEditing(false);
                  }}
                >
                  Save
                </Button>
                <Button size="sm" variant="outline" onClick={() => setEditing(false)}>
                  Cancel
                </Button>
              </>
            ) : (
              <>
                <Button size="sm" onClick={() => onApprove(draft.id)} disabled={loading}>
                  {loading ? "Sending..." : "Approve & Send"}
                </Button>
                <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
                  Edit
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-destructive hover:text-destructive"
                  onClick={() => onReject(draft.id)}
                  disabled={loading}
                >
                  Reject
                </Button>
              </>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
