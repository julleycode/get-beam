import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Safe markdown renderer for blog post bodies.
 *
 * No `rehype-raw` → raw HTML in the source is NOT rendered, so post bodies
 * cannot inject markup/scripts. Element styling is done via the `components`
 * map (the project has no @tailwindcss/typography plugin).
 */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="max-w-none text-[15px] leading-7 text-foreground/90">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: (props) => (
            <h1 className="mt-10 mb-4 font-serif text-3xl font-semibold tracking-tight" {...props} />
          ),
          h2: (props) => (
            <h2 className="mt-9 mb-3 font-serif text-2xl font-semibold tracking-tight" {...props} />
          ),
          h3: (props) => (
            <h3 className="mt-7 mb-2 text-xl font-semibold" {...props} />
          ),
          p: (props) => <p className="my-4" {...props} />,
          ul: (props) => <ul className="my-4 list-disc pl-6 space-y-1" {...props} />,
          ol: (props) => <ol className="my-4 list-decimal pl-6 space-y-1" {...props} />,
          li: (props) => <li className="leading-7" {...props} />,
          a: (props) => (
            <a className="text-[hsl(345,100%,45%)] underline underline-offset-2 hover:opacity-80" {...props} />
          ),
          blockquote: (props) => (
            <blockquote className="my-4 border-l-2 border-[hsl(345,100%,60%)] pl-4 italic text-muted-foreground" {...props} />
          ),
          code: (props) => (
            <code className="rounded bg-secondary px-1.5 py-0.5 font-mono text-[13px]" {...props} />
          ),
          hr: () => <hr className="my-8 border-[rgba(43,37,48,0.12)]" />,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
