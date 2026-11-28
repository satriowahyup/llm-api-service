import { useEffect, useMemo, useState } from "react";
import { formatTimestamp, formatUsd } from "../lib/format";
import type { SessionSummary } from "../types/api";

interface SessionSidebarProps {
  sessions: SessionSummary[];
  activeSessionId: string | null;
  loading: boolean;
  error: string | null;
  mobileOpen: boolean;
  onCloseMobile: () => void;
  onNewSession: () => void;
  onSelectSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => Promise<void>;
  onRetryLoad: () => void;
}

export function SessionSidebar({
  sessions,
  activeSessionId,
  loading,
  error,
  mobileOpen,
  onCloseMobile,
  onNewSession,
  onSelectSession,
  onDeleteSession,
  onRetryLoad,
}: SessionSidebarProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    if (!mobileOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onCloseMobile();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [mobileOpen, onCloseMobile]);

  const filteredSessions = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return sessions;
    return sessions.filter(
      (item) =>
        (item.title || "").toLowerCase().includes(q) ||
        item.provider.toLowerCase().includes(q) ||
        item.model.toLowerCase().includes(q),
    );
  }, [sessions, searchQuery]);

  const workspaceTotals = useMemo(() => {
    let tokens = 0;
    let cost = 0;
    for (const s of sessions) {
      tokens += s.total_tokens;
      cost += s.total_cost_usd;
    }
    return { tokens, cost };
  }, [sessions]);

  const handleConfirmDelete = async (sessionId: string) => {
    setDeletingId(sessionId);
    try {
      await onDeleteSession(sessionId);
    } finally {
      setDeletingId(null);
      setConfirmDeleteId(null);
    }
  };

  const sidebarContent = (
    <nav
      aria-label="Chat sessions"
      className="flex h-full flex-col border-r"
      style={{
        backgroundColor: "var(--bg-rail)",
        borderColor: "var(--border-subtle)",
      }}
    >
      <div
        className="space-y-2 border-b p-3"
        style={{ borderColor: "var(--border-subtle)" }}
      >
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => {
              onNewSession();
              onCloseMobile();
            }}
            className="flex min-h-[44px] flex-1 items-center justify-between rounded-md px-3 py-2 text-sm font-semibold transition-colors"
            style={{
              backgroundColor: "var(--accent)",
              color: "var(--accent-ink)",
            }}
          >
            <span>New Session</span>
            <span className="font-mono-tech text-[11px] opacity-85">Ctrl+K</span>
          </button>
          <button
            type="button"
            onClick={onCloseMobile}
            aria-label="Close session drawer"
            className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-md border px-2 text-xs font-semibold lg:hidden"
            style={{
              borderColor: "var(--border-strong)",
              color: "var(--ink-primary)",
              backgroundColor: "var(--bg-surface)",
            }}
          >
            Close
          </button>
        </div>

        <div className="relative">
          <label htmlFor="session-search" className="sr-only">
            Filter sessions
          </label>
          <input
            id="session-search"
            type="search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Filter by title or provider..."
            className="min-h-[38px] w-full rounded-md border px-2.5 py-1.5 text-xs"
            style={{
              backgroundColor: "var(--bg-surface)",
              borderColor: "var(--border-subtle)",
              color: "var(--ink-primary)",
            }}
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {loading && sessions.length === 0 ? (
          <p className="px-2 py-4 text-xs" style={{ color: "var(--ink-secondary)" }}>
            Loading sessions...
          </p>
        ) : error ? (
          <div
            role="alert"
            className="rounded-md border p-3 text-xs"
            style={{
              borderColor: "var(--danger)",
              backgroundColor: "var(--danger-soft)",
              color: "var(--ink-primary)",
            }}
          >
            <p className="font-semibold">Could not load sessions</p>
            <p className="mt-1" style={{ color: "var(--ink-secondary)" }}>
              {error}
            </p>
            <button
              type="button"
              onClick={onRetryLoad}
              className="mt-2 min-h-[38px] rounded border px-3 py-1 text-xs font-semibold"
              style={{
                borderColor: "var(--border-strong)",
                backgroundColor: "var(--bg-surface)",
                color: "var(--ink-primary)",
              }}
            >
              Retry
            </button>
          </div>
        ) : sessions.length === 0 ? (
          <div className="px-2 py-6 text-xs" style={{ color: "var(--ink-secondary)" }}>
            <p className="font-semibold" style={{ color: "var(--ink-primary)" }}>
              No saved sessions
            </p>
            <p className="mt-1 leading-relaxed">
              Send a prompt to create a persistent conversation with token and cost telemetry.
            </p>
          </div>
        ) : filteredSessions.length === 0 ? (
          <div className="px-2 py-5 text-xs" style={{ color: "var(--ink-secondary)" }}>
            <p>No sessions match "{searchQuery}".</p>
            <button
              type="button"
              onClick={() => setSearchQuery("")}
              className="mt-2 font-semibold underline"
              style={{ color: "var(--accent)" }}
            >
              Clear filter
            </button>
          </div>
        ) : (
          <ul className="space-y-1">
            {filteredSessions.map((session) => {
              const isActive = session.id === activeSessionId;
              const isConfirming = confirmDeleteId === session.id;
              const isDeleting = deletingId === session.id;

              return (
                <li
                  key={session.id}
                  className="rounded-md border transition-colors"
                  style={{
                    backgroundColor: isActive ? "var(--bg-surface)" : "transparent",
                    borderColor: isActive ? "var(--accent)" : "transparent",
                  }}
                >
                  <div className="flex items-start gap-1 px-2.5 py-2">
                    <button
                      type="button"
                      onClick={() => {
                        onSelectSession(session.id);
                        onCloseMobile();
                      }}
                      className="min-h-[44px] min-w-0 flex-1 text-left"
                    >
                      <p
                        className="truncate text-[13px] font-medium leading-snug"
                        style={{ color: "var(--ink-primary)" }}
                      >
                        {session.title || "Untitled session"}
                      </p>
                      <div
                        className="font-mono-tech mt-1 flex items-center justify-between gap-2 text-[11px]"
                        style={{ color: "var(--ink-secondary)" }}
                      >
                        <span className="truncate">
                          {session.provider} · {session.message_count}m
                        </span>
                        <span className="shrink-0">{formatUsd(session.total_cost_usd)}</span>
                      </div>
                      <p className="mt-0.5 text-[10px]" style={{ color: "var(--ink-muted)" }}>
                        {formatTimestamp(session.updated_at)}
                      </p>
                    </button>

                    {!isConfirming && (
                      <button
                        type="button"
                        onClick={() => setConfirmDeleteId(session.id)}
                        aria-label={`Delete session ${session.title || session.id}`}
                        className="min-h-[36px] shrink-0 rounded px-1.5 py-1 text-[11px] font-medium hover:underline"
                        style={{ color: "var(--danger)" }}
                      >
                        Del
                      </button>
                    )}
                  </div>

                  {isConfirming && (
                    <div
                      className="flex items-center justify-between gap-2 border-t px-2.5 py-1.5"
                      style={{ borderColor: "var(--border-subtle)" }}
                    >
                      <span className="text-[11px] font-medium" style={{ color: "var(--danger)" }}>
                        Delete session?
                      </span>
                      <div className="flex items-center gap-1.5">
                        <button
                          type="button"
                          disabled={isDeleting}
                          onClick={() => void handleConfirmDelete(session.id)}
                          className="min-h-[32px] rounded px-2 py-0.5 text-[11px] font-semibold"
                          style={{
                            backgroundColor: "var(--danger)",
                            color: "#ffffff",
                          }}
                        >
                          {isDeleting ? "..." : "Confirm"}
                        </button>
                        <button
                          type="button"
                          disabled={isDeleting}
                          onClick={() => setConfirmDeleteId(null)}
                          className="min-h-[32px] rounded border px-2 py-0.5 text-[11px] font-medium"
                          style={{
                            borderColor: "var(--border-strong)",
                            color: "var(--ink-primary)",
                          }}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <footer
        className="border-t px-3 py-2.5"
        style={{
          borderColor: "var(--border-subtle)",
          backgroundColor: "var(--bg-surface)",
        }}
      >
        <p className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--ink-muted)" }}>
          Loaded Workspace Spend
        </p>
        <div className="font-mono-tech mt-1 flex items-baseline justify-between text-xs">
          <span style={{ color: "var(--ink-secondary)" }}>
            {sessions.length} {sessions.length === 1 ? "session" : "sessions"} ·{" "}
            {workspaceTotals.tokens.toLocaleString()} tok
          </span>
          <span className="font-semibold" style={{ color: "var(--ink-primary)" }}>
            {formatUsd(workspaceTotals.cost)}
          </span>
        </div>
      </footer>
    </nav>
  );

  return (
    <>
      <aside className="hidden w-68 shrink-0 lg:block">{sidebarContent}</aside>

      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 flex lg:hidden"
          role="dialog"
          aria-modal="true"
          aria-label="Session navigation"
        >
          <div className="w-80 max-w-[85vw]">{sidebarContent}</div>
          <button
            type="button"
            aria-label="Dismiss session drawer"
            onClick={onCloseMobile}
            className="flex-1 bg-black/45"
          />
        </div>
      )}
    </>
  );
}
