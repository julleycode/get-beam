"use client";

import type { RefObject } from "react";

// A formatting toolbar over the body <textarea>. Inserts markdown at the
// selection — rich-editing feel, but the stored value stays clean markdown
// (no lossy WYSIWYG serialization round-trip).

interface Props {
  textareaRef: RefObject<HTMLTextAreaElement>;
  value: string;
  onChange: (next: string) => void;
}

function restoreSelection(ta: HTMLTextAreaElement, start: number, end: number) {
  requestAnimationFrame(() => {
    ta.focus();
    ta.selectionStart = start;
    ta.selectionEnd = end;
  });
}

/** Wrap the current selection (or a placeholder) with `before`/`after`. */
function wrap(
  ta: HTMLTextAreaElement,
  value: string,
  onChange: (v: string) => void,
  before: string,
  after: string,
  placeholder = "text"
) {
  const start = ta.selectionStart;
  const end = ta.selectionEnd;
  const selected = value.slice(start, end) || placeholder;
  const next = value.slice(0, start) + before + selected + after + value.slice(end);
  onChange(next);
  restoreSelection(ta, start + before.length, start + before.length + selected.length);
}

/** Prepend `prefix` to the start of the selection's first line. */
function linePrefix(
  ta: HTMLTextAreaElement,
  value: string,
  onChange: (v: string) => void,
  prefix: string
) {
  const start = ta.selectionStart;
  const lineStart = value.lastIndexOf("\n", start - 1) + 1;
  const next = value.slice(0, lineStart) + prefix + value.slice(lineStart);
  onChange(next);
  restoreSelection(ta, start + prefix.length, ta.selectionEnd + prefix.length);
}

export function MarkdownToolbar({ textareaRef, value, onChange }: Props) {
  const actions: { label: string; title: string; run: (ta: HTMLTextAreaElement) => void }[] = [
    { label: "B", title: "Bold", run: (ta) => wrap(ta, value, onChange, "**", "**") },
    { label: "I", title: "Italic", run: (ta) => wrap(ta, value, onChange, "*", "*") },
    { label: "H2", title: "Heading 2", run: (ta) => linePrefix(ta, value, onChange, "## ") },
    { label: "H3", title: "Heading 3", run: (ta) => linePrefix(ta, value, onChange, "### ") },
    { label: "Link", title: "Link", run: (ta) => wrap(ta, value, onChange, "[", "](https://)", "label") },
    { label: "• List", title: "Bullet list", run: (ta) => linePrefix(ta, value, onChange, "- ") },
    { label: "1. List", title: "Numbered list", run: (ta) => linePrefix(ta, value, onChange, "1. ") },
    { label: "❝", title: "Quote", run: (ta) => linePrefix(ta, value, onChange, "> ") },
    { label: "</>", title: "Code", run: (ta) => wrap(ta, value, onChange, "`", "`", "code") },
  ];

  return (
    <div className="flex flex-wrap gap-1 rounded-t-md border border-b-0 border-[rgba(43,37,48,0.16)] bg-secondary/50 p-1">
      {actions.map((a) => (
        <button
          key={a.label}
          type="button"
          title={a.title}
          aria-label={a.title}
          onClick={() => {
            const ta = textareaRef.current;
            if (ta) a.run(ta);
          }}
          className="rounded px-2 py-0.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-card hover:text-foreground"
        >
          {a.label}
        </button>
      ))}
    </div>
  );
}
