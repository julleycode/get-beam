"use client";

import type { SocialPost as Post } from "@/lib/api";
import { PlatformBadge } from "./platform-badge";

interface PostCardProps {
  post: Post;
  onGenerateDraft: (postId: string) => void;
  loading?: boolean;
}

export function PostCard({ post, onGenerateDraft, loading }: PostCardProps) {
  const timeAgo = getTimeAgo(post.posted_at);

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center text-xs font-bold">
            {post.author_name.charAt(0).toUpperCase()}
          </div>
          <div>
            <p className="text-sm font-medium">{post.author_name}</p>
            <p className="text-xs text-gray-400">@{post.author_username}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <PlatformBadge platform={post.platform} />
          <span className="text-xs text-gray-400">{timeAgo}</span>
        </div>
      </div>

      {post.content && (
        <p className="text-sm text-gray-700 leading-relaxed">{post.content}</p>
      )}

      <div className="flex items-center justify-between pt-1">
        {post.post_url && (
          <a
            href={post.post_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-[#FF5C82] hover:underline"
          >
            View original
          </a>
        )}
        <button
          onClick={() => onGenerateDraft(post.id)}
          disabled={post.commented || loading}
          className={
            post.commented
              ? "text-xs px-3 py-1.5 rounded-md bg-green-50 text-green-600 cursor-default"
              : "text-xs px-3 py-1.5 rounded-md bg-[#FF3366] text-white hover:bg-[#E51F50] disabled:opacity-50"
          }
        >
          {post.commented ? "Commented" : loading ? "Generating..." : "Generate Reply"}
        </button>
      </div>
    </div>
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
