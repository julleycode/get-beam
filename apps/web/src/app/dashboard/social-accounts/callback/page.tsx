"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import Link from "next/link";

function CallbackContent() {
  const params = useSearchParams();
  const success = params.get("success");
  const error = params.get("error");
  const platform = params.get("platform") || "unknown";
  const username = params.get("username");
  const postReady = params.get("post_ready"); // "true" | "false" | null (unknown)

  return (
    <div className="max-w-md mx-auto mt-20 text-center space-y-4">
      {success ? (
        <>
          <div className="w-16 h-16 mx-auto rounded-full bg-green-100 flex items-center justify-center">
            <svg className="w-8 h-8 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h1 className="text-xl font-bold text-gray-900">Connected!</h1>
          <p className="text-gray-500">
            Successfully connected <span className="font-medium capitalize">{platform}</span>
            {username && <> as <span className="font-medium">{username}</span></>}.
          </p>
          {postReady === "true" && (
            <p className="text-sm font-medium text-green-600">
              ✓ Ready to post — this account can send replies.
            </p>
          )}
          {postReady === "false" && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-left text-sm text-amber-800">
              Connected, but this account can&apos;t post yet — its app
              permissions look read-only. Check the {platform} app&apos;s write
              access, then reconnect.
            </div>
          )}
        </>
      ) : (
        <>
          <div className="w-16 h-16 mx-auto rounded-full bg-red-100 flex items-center justify-center">
            <svg className="w-8 h-8 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </div>
          <h1 className="text-xl font-bold text-gray-900">Connection Failed</h1>
          <p className="text-gray-500">
            Could not connect to <span className="font-medium capitalize">{platform}</span>.
          </p>
          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700 text-left">
              {error}
            </div>
          )}
        </>
      )}

      <Link
        href="/dashboard/social-accounts"
        className="inline-block mt-4 px-4 py-2 bg-[#FF3366] text-white rounded-lg hover:bg-[#E51F50] text-sm"
      >
        Back to Accounts
      </Link>
    </div>
  );
}

export default function CallbackPage() {
  return (
    <Suspense fallback={<div className="text-center mt-20 text-gray-400">Processing...</div>}>
      <CallbackContent />
    </Suspense>
  );
}
