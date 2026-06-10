"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Platform } from "@/lib/api";
import { ListCardSkeleton } from "@/components/skeletons";
import { ErrorBanner } from "@/components/error-banner";
import { PlatformBadge } from "@/components/platform-badge";

const ALL_PLATFORMS: { platform: Platform; label: string; color: string }[] = [
  { platform: "twitter", label: "Twitter / X", color: "bg-sky-500" },
  { platform: "facebook", label: "Facebook", color: "bg-blue-600" },
  { platform: "instagram", label: "Instagram", color: "bg-pink-500" },
  { platform: "linkedin", label: "LinkedIn", color: "bg-blue-700" },
  { platform: "tiktok", label: "TikTok", color: "bg-gray-900" },
];

export default function SocialAccountsPage() {
  const queryClient = useQueryClient();

  const { data: accounts, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["social-accounts"],
    queryFn: () => api.getSocialAccounts(),
  });

  const connectMut = useMutation({
    mutationFn: (platform: Platform) => api.connectPlatform(platform),
    onSuccess: (data) => {
      window.open(data.auth_url, "_blank");
    },
    onError: (error: Error) => {
      alert(
        error.message ||
          "Failed to connect. Check your OAuth credentials in .env"
      );
    },
  });

  const disconnectMut = useMutation({
    mutationFn: (accountId: string) => api.disconnectAccount(accountId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["social-accounts"] }),
  });

  const connectedPlatforms = new Set(accounts?.map((a) => a.platform) ?? []);

  return (
    <div className="max-w-3xl space-y-6">
      <h1 className="text-2xl font-serif font-semibold tracking-tight">Connected Accounts</h1>

      {isLoading ? (
        <ListCardSkeleton rows={3} leading />
      ) : isError ? (
        <ErrorBanner
          message={`Couldn't load accounts — ${error?.message ?? "request failed"}`}
          onRetry={() => refetch()}
        />
      ) : accounts && accounts.length > 0 ? (
        <div className="space-y-3">
          {accounts.map((account) => (
            <div
              key={account.id}
              className="bg-white rounded-lg border border-gray-200 p-4 flex items-center justify-between"
            >
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-gray-200 flex items-center justify-center text-sm font-bold">
                  {account.username.charAt(0).toUpperCase()}
                </div>
                <div>
                  <p className="text-sm font-medium">{account.username}</p>
                  <PlatformBadge platform={account.platform} />
                </div>
              </div>
              <button
                onClick={() => disconnectMut.mutate(account.id)}
                disabled={disconnectMut.isPending}
                className="text-xs px-3 py-1.5 rounded-md border border-red-200 text-red-600 hover:bg-red-50"
              >
                Disconnect
              </button>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-gray-400">
          No accounts connected yet. Connect one below.
        </p>
      )}

      <div>
        <h2 className="text-lg font-semibold mb-3">Connect a Platform</h2>
        <div className="grid grid-cols-2 gap-3">
          {ALL_PLATFORMS.map(({ platform, label, color }) => {
            const connected = connectedPlatforms.has(platform);
            return (
              <button
                key={platform}
                onClick={() => !connected && connectMut.mutate(platform)}
                disabled={connected || connectMut.isPending}
                className={`flex items-center gap-3 p-4 rounded-lg border text-left transition-colors ${
                  connected
                    ? "border-green-200 bg-green-50 cursor-default"
                    : "border-gray-200 bg-white hover:border-[#FFA8BD] hover:bg-[#FFF1F5]"
                }`}
              >
                <div
                  className={`w-8 h-8 rounded-md ${color} flex items-center justify-center text-white text-xs font-bold`}
                >
                  {label.charAt(0)}
                </div>
                <div>
                  <p className="text-sm font-medium">{label}</p>
                  <p className="text-xs text-gray-400">
                    {connected ? "Connected" : "Click to connect"}
                  </p>
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
