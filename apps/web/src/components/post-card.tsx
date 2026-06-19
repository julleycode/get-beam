"use client";

import { Check } from "lucide-react";
import type { SocialPost as Post } from "@/lib/api";
import { PlatformBadge } from "./platform-badge";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

interface PostCardProps {
  post: Post;
  onGenerateDraft: (postId: string) => void;
  loading?: boolean;
}

export function PostCard({ post, onGenerateDraft, loading }: PostCardProps) {
  const timeAgo = getTimeAgo(post.posted_at);

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-secondary text-xs font-bold text-secondary-foreground">
              {post.author_name.charAt(0).toUpperCase()}
            </div>
            <div>
              <p className="text-sm font-medium">{post.author_name}</p>
              <p className="text-xs text-muted-foreground">@{post.author_username}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <PlatformBadge platform={post.platform} />
            <span className="text-xs text-muted-foreground">{timeAgo}</span>
          </div>
        </div>

        {post.content && (
          <p className="text-sm leading-relaxed text-foreground">{post.content}</p>
        )}

        <div className="flex items-center justify-between pt-1">
          {post.post_url ? (
            <a
              href={post.post_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-primary hover:underline"
            >
              View original
            </a>
          ) : (
            <span />
          )}
          {post.commented ? (
            <Button size="sm" variant="ghost" disabled className="text-success">
              <Check className="mr-1 h-3.5 w-3.5" />
              Commented
            </Button>
          ) : (
            <Button
              size="sm"
              onClick={() => onGenerateDraft(post.id)}
              disabled={loading}
            >
              {loading ? "Generating..." : "Generate Reply"}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function getTimeAgo(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const seconds = Math.floor((now - then) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
