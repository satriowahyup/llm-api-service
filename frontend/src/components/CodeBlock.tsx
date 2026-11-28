import { useState, type ReactNode } from "react";

interface CodeBlockProps {
  className?: string;
  children?: ReactNode;
}

function extractText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") {
    return String(node);
  }
  if (Array.isArray(node)) {
    return node.map(extractText).join("");
  }
  if (node && typeof node === "object" && "props" in node) {
    const props = (node as { props?: { children?: ReactNode } }).props;
    return extractText(props?.children);
  }
  return "";
}

export function MarkdownPre({ children }: { children?: ReactNode }) {
  const [copied, setCopied] = useState(false);

  let language = "code";
  if (children && typeof children === "object" && "props" in children) {
    const childProps = (children as { props?: CodeBlockProps }).props;
    const match = /language-([\w-]+)/.exec(childProps?.className || "");
    if (match?.[1]) {
      language = match[1];
    }
  }

  const rawCode = extractText(children).replace(/\n$/, "");

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(rawCode);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      // Clipboard API unavailable in restricted context
    }
  };

  return (
    <div
      className="my-2.5 overflow-hidden rounded-md border"
      style={{
        backgroundColor: "var(--bg-subtle)",
        borderColor: "var(--border-subtle)",
      }}
    >
      <div
        className="flex items-center justify-between border-b px-3 py-1.5"
        style={{
          borderColor: "var(--border-subtle)",
          backgroundColor: "var(--bg-rail)",
        }}
      >
        <span
          className="font-mono-tech text-[11px] font-medium"
          style={{ color: "var(--ink-secondary)" }}
        >
          {language}
        </span>
        <button
          type="button"
          onClick={() => void handleCopy()}
          aria-label={`Copy ${language} code block`}
          className="font-mono-tech min-h-[28px] rounded border px-2 py-0.5 text-[11px] font-medium transition-colors"
          style={{
            borderColor: copied ? "var(--accent)" : "var(--border-strong)",
            backgroundColor: copied ? "var(--accent-soft)" : "var(--bg-surface)",
            color: "var(--ink-primary)",
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre>{children}</pre>
    </div>
  );
}
