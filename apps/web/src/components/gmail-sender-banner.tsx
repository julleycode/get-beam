"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Mail } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";

/**
 * Connect-Gmail control for the Campaigns page. Lets the site owner send
 * campaign email from their own Gmail (no "via sendgrid.info") instead of Beam's
 * shared address. Hidden entirely when the server has no Google OAuth configured.
 */
export function GmailSenderBanner() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const [notice, setNotice] = useState<string | null>(null);

  const { data } = useQuery({
    queryKey: ["email-sender-status"],
    queryFn: () => api.getEmailSenderStatus(),
  });

  // Surface the OAuth callback result (?gmail_connected / ?gmail_error).
  useEffect(() => {
    const connected = searchParams.get("gmail_connected");
    const error = searchParams.get("gmail_error");
    if (connected) {
      setNotice(`Connected — campaigns will now send from ${connected}.`);
      queryClient.invalidateQueries({ queryKey: ["email-sender-status"] });
    } else if (error) {
      setNotice(error);
    }
  }, [searchParams, queryClient]);

  const connect = useMutation({
    mutationFn: () => api.connectGmail(),
    onSuccess: (res) => {
      window.location.href = res.auth_url;
    },
    onError: () => setNotice("Couldn't start the Gmail connect flow. Try again."),
  });

  const disconnect = useMutation({
    mutationFn: () => api.disconnectGmail(),
    onSuccess: () => {
      setNotice("Disconnected. Campaigns now send via Beam.");
      queryClient.invalidateQueries({ queryKey: ["email-sender-status"] });
    },
  });

  // Nothing to show until we know status, and stay hidden if the server has no
  // Google OAuth configured (feature effectively off).
  if (!data || !data.configured) return null;

  return (
    <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border bg-secondary px-4 py-3 text-sm">
      {data.connected ? (
        <>
          <CheckCircle2 className="h-4 w-4 text-success" />
          <span>
            Campaigns send from <strong>{data.email}</strong>
          </span>
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto"
            onClick={() => disconnect.mutate()}
            disabled={disconnect.isPending}
          >
            Disconnect
          </Button>
        </>
      ) : (
        <>
          <Mail className="h-4 w-4 text-muted-foreground" />
          <span className="text-muted-foreground">
            Campaigns send via Beam. Connect your Gmail to send from your own address.
          </span>
          <Button
            size="sm"
            className="ml-auto"
            onClick={() => connect.mutate()}
            disabled={connect.isPending}
          >
            Connect Gmail
          </Button>
        </>
      )}
      {notice && <span className="w-full text-xs text-muted-foreground">{notice}</span>}
    </div>
  );
}
