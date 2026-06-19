"use client";

import { useState } from "react";
import { Sparkles, ArrowUp } from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const SUGGESTIONS = [
  "What should I focus on today?",
  "Summarize my visitors this week",
  "Who's worth reaching out to?",
];

/** The Clay-style "ask Beam anything" box — input + suggestion chips + answer.
 *  Backed by the real /api/v1/ai/ask Gemini endpoint. */
export function AskAi({ siteId }: { siteId?: string }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(q: string) {
    const trimmed = q.trim();
    if (!trimmed || loading) return;
    setLoading(true);
    setError(null);
    setAnswer(null);
    try {
      const res = await api.askAI(trimmed, siteId);
      setAnswer(res.answer);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong — try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-3">
      <Card className="p-2">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit(question);
          }}
          className="flex items-center gap-2"
        >
          <Sparkles className="ml-2 h-5 w-5 shrink-0 text-primary" />
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask Beam anything, or describe what you'd like to do…"
            className="flex-1 bg-transparent py-2 text-sm outline-none placeholder:text-muted-foreground"
          />
          <Button
            type="submit"
            size="icon"
            disabled={loading || !question.trim()}
            aria-label="Ask"
          >
            <ArrowUp className="h-4 w-4" />
          </Button>
        </form>
      </Card>

      <div className="flex flex-wrap gap-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => {
              setQuestion(s);
              submit(s);
            }}
            disabled={loading}
            className="rounded-full border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-50"
          >
            {s}
          </button>
        ))}
      </div>

      {(loading || answer || error) && (
        <Card>
          <CardContent className="p-4 text-sm">
            {loading ? (
              <p className="flex items-center gap-2 text-muted-foreground">
                <Sparkles className="h-4 w-4 animate-pulse text-primary" />
                Thinking…
              </p>
            ) : error ? (
              <p className="text-destructive">{error}</p>
            ) : (
              <p className="whitespace-pre-wrap leading-relaxed text-foreground">
                {answer}
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
