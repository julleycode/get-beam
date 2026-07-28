// Plain-language explainers shown in the ⓘ next to each dashboard page title
// (PageHeader `info` prop). The persistent, in-page counterpart to the one-time
// per-tab intro dialog — a reader can re-check "what is this page for / how is
// it computed" without replaying the tour. Keep copy faithful to behaviour:
//   • intent scoring lives in <IntentScoreInfo> (visitors table column)
//   • agent detection: apps/api/services/agent_classifier.py + agent_verification.py
//   • outreach guardrail: draft → approve → send, never auto-send

function Help({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <p className="font-medium text-foreground">{title}</p>
      {children}
    </div>
  );
}

export function VisitorsHelp() {
  return (
    <Help title="Who's on your site">
      <p className="text-muted-foreground">
        Every visitor Beam captured, ranked by an intent score (0–100). Hover the{" "}
        <span className="font-medium text-foreground">Intent ⓘ</span> in the table
        for the full formula.
      </p>
      <ul className="space-y-1 text-muted-foreground">
        <li>
          <span className="font-medium text-foreground">Identified</span> — resolved
          to a real person (needs intent 20+).
        </li>
        <li>
          <span className="font-medium text-foreground">Enriched</span> — LinkedIn,
          role and company added.
        </li>
        <li>Badges flag returning, AI-referred, outlier and bot-suspect traffic.</li>
      </ul>
    </Help>
  );
}

export function AgentsHelp() {
  return (
    <Help title="AI agents on your site">
      <p className="text-muted-foreground">
        Visits from AI crawlers (GPTBot, ClaudeBot, PerplexityBot…), kept fully
        separate from human visitors — never a contactable lead.
      </p>
      <ul className="space-y-1 text-muted-foreground">
        <li>
          <span className="font-medium text-foreground">Verification:</span>{" "}
          UA-only (name only) → IP-verified → rDNS-verified, strongest last.
        </li>
        <li>
          <span className="font-medium text-foreground">Agent → company:</span> a
          qualifying agent IP can resolve to a real company as an ordinary lead.
        </li>
        <li>
          <span className="font-medium text-foreground">GEO / AEO:</span> which
          vendors cite you and which pages they read.
        </li>
      </ul>
    </Help>
  );
}

export function SegmentsHelp() {
  return (
    <Help title="Group your audience">
      <p className="text-muted-foreground">
        AI groups your visitors into segments from behaviour and identity, each
        with a suggested messaging angle and channels.
      </p>
      <ul className="space-y-1 text-muted-foreground">
        <li>Pick a site, then Re-run segmentation to refresh the groups.</li>
        <li>Turn any segment into a campaign in one click.</li>
      </ul>
    </Help>
  );
}

export function CampaignsHelp() {
  return (
    <Help title="Reach your segments">
      <p className="text-muted-foreground">
        Email and social touchpoints built from a segment. Beam drafts — you
        approve and send.
      </p>
      <ul className="space-y-1 text-muted-foreground">
        <li>Flow: draft → approved → active. Nothing sends without your approval.</li>
        <li>Every email carries an unsubscribe link; suppression is enforced.</li>
      </ul>
    </Help>
  );
}

export function ConnectorsHelp() {
  return (
    <Help title="Move your data">
      <p className="text-muted-foreground">One place for data in and out of Beam.</p>
      <ul className="space-y-1 text-muted-foreground">
        <li>Export a segment as CSV for ad platforms.</li>
        <li>Push identified visitors into your CRM.</li>
        <li>Import a known-contacts list to match against visitors.</li>
      </ul>
    </Help>
  );
}

export function FeedHelp() {
  return (
    <Help title="Social content">
      <p className="text-muted-foreground">
        Draft, review and publish social posts. Pairs with Drafts (AI replies) and
        Social Accounts (where they post).
      </p>
    </Help>
  );
}

export function DraftsHelp() {
  return (
    <Help title="AI-drafted replies">
      <p className="text-muted-foreground">
        Suggested outreach waiting for your review. Approve to send, edit first, or
        skip — Beam never sends on its own.
      </p>
    </Help>
  );
}

export function SocialAccountsHelp() {
  return (
    <Help title="Connect your socials">
      <p className="text-muted-foreground">
        Link the accounts Beam engages from. Replies and posts you approve go out
        from these connected profiles.
      </p>
    </Help>
  );
}
