// Display labels for AI-referral attribution sources (Visitor.ai_source).
// The backend stores short lowercase keys (classify_ai_source in
// apps/api/services/ai_referral.py); the dashboard renders these labels.
// Attribution-only metadata — never affects emailability.

export const AI_SOURCE_LABELS: Record<string, string> = {
  chatgpt: "ChatGPT",
  perplexity: "Perplexity",
  gemini: "Gemini",
  copilot: "Copilot",
  claude: "Claude",
  you: "You.com",
  grok: "Grok",
  deepseek: "DeepSeek",
  mistral: "Mistral",
};

// Human-readable label for an ai_source key, falling back to the raw key.
export function aiSourceLabel(source: string | null | undefined): string {
  if (!source) return "";
  return AI_SOURCE_LABELS[source] ?? source;
}
