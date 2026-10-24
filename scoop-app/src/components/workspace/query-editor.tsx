"use client";

import * as React from "react";
import { PlayIcon, TriangleAlertIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Kbd, KbdGroup } from "@/components/ui/kbd";
import { Spinner } from "@/components/ui/spinner";
import { useTabConnector } from "@/lib/workspace/use-active-connector";
import { useGenerateQuery } from "@/lib/workspace/use-generate-query";
import { formatQuery, isQuery, parseQuery } from "@/lib/workspace/query";
import { useRunQuery } from "@/lib/workspace/use-run-query";
import { useWorkspace, type Tab } from "@/lib/workspace/store";

const INDENT = "  ";

export function QueryEditor({ tab }: { tab: Tab }) {
  const { dispatch } = useWorkspace();
  const runQuery = useRunQuery();
  const { generate, cancel } = useGenerateQuery();
  const { connector, stale } = useTabConnector();
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);
  // The editor is shared by all tabs; generation outlives a tab switch.
  const tabIdRef = React.useRef(tab.id);
  React.useEffect(() => {
    tabIdRef.current = tab.id;
  }, [tab.id]);
  const running = tab.run.status === "running";
  const generating = tab.assist.status === "running";

  const run = () => {
    if (!connector || running || !tab.text.trim()) return;
    const { query, error } = parseQuery(tab.text);
    if (query) {
      void runQuery(tab.id, connector.id, query);
      return;
    }
    dispatch({
      type: "runRejected",
      id: tab.id,
      error: new Error(
        `Not a query: ${error} Press Tab to have the assistant write one.`,
      ),
    });
  };

  /**
   * Replace the editor's text with a query the assistant authors. The request
   * is the selection, or the whole text when it isn't already a query; the
   * rest of the text goes along as the query to refine.
   */
  const startGenerating = async () => {
    const el = textareaRef.current;
    if (!el || !connector || generating) return;
    const { selectionStart, selectionEnd, value } = el;
    const selected = selectionStart !== selectionEnd;
    const prompt = selected ? value.slice(selectionStart, selectionEnd) : value;
    if (!prompt.trim() || (!selected && isQuery(value))) return;
    const rest = selected
      ? (value.slice(0, selectionStart) + value.slice(selectionEnd)).trim()
      : "";

    const tabId = tab.id;
    const query = await generate(
      tabId,
      connector.id,
      prompt,
      rest || undefined,
    );
    if (query === undefined) return;
    const text = formatQuery(query);

    const current = textareaRef.current;
    if (current && tabIdRef.current === tabId && current.value === value) {
      // React hasn't re-rendered since generation finished; insertText is
      // refused while the textarea is still read-only.
      current.readOnly = false;
      current.focus();
      current.setSelectionRange(0, value.length);
      // Inserting through the browser keeps the edit on its undo stack, so ⌘Z
      // brings the request back. onChange syncs the store.
      if (document.execCommand("insertText", false, text)) return;
    }
    dispatch({ type: "setText", id: tabId, text });
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      run();
    } else if (e.key === "Escape" && generating) {
      e.preventDefault();
      cancel(tab.id);
    } else if (
      e.key === "Tab" &&
      !e.shiftKey &&
      !e.metaKey &&
      !e.ctrlKey &&
      !e.altKey
    ) {
      e.preventDefault();
      void startGenerating();
    } else if (e.key === "Tab" && e.shiftKey) {
      e.preventDefault();
      if (generating) return;
      const el = e.currentTarget;
      const { selectionStart: start, selectionEnd: end, value } = el;
      const text = value.slice(0, start) + INDENT + value.slice(end);
      dispatch({ type: "setText", id: tab.id, text });
      requestAnimationFrame(() => {
        el.selectionStart = el.selectionEnd = start + INDENT.length;
      });
    }
  };

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      {stale && (
        <span
          className="absolute top-2 left-3 z-10 flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400"
          title="This tab's connector no longer exists"
        >
          <TriangleAlertIcon className="size-3.5" />
          Connector missing
        </span>
      )}
      <textarea
        ref={textareaRef}
        value={tab.text}
        onChange={(e) =>
          dispatch({ type: "setText", id: tab.id, text: e.target.value })
        }
        onKeyDown={onKeyDown}
        readOnly={generating}
        aria-busy={generating}
        placeholder="Describe a query and press Tab, or write its JSON"
        spellCheck={false}
        autoCapitalize="off"
        autoCorrect="off"
        aria-label="Query JSON"
        className="min-h-0 flex-1 resize-none bg-background p-3 pb-12 font-mono text-sm leading-relaxed outline-none placeholder:text-muted-foreground read-only:text-muted-foreground"
      />
      <div
        className="absolute bottom-2 left-3 flex max-w-[60%] items-center gap-2 text-xs text-muted-foreground"
        aria-live="polite"
      >
        {generating ? (
          <>
            <Spinner className="size-3.5 shrink-0" />
            <span className="truncate">{tab.assist.step ?? "Thinking…"}</span>
            <Button size="xs" variant="ghost" onClick={() => cancel(tab.id)}>
              Cancel
              <Kbd>Esc</Kbd>
            </Button>
          </>
        ) : tab.assist.status === "error" ? (
          <span
            className="flex min-w-0 items-center gap-1 text-amber-600 dark:text-amber-400"
            title={tab.assist.error}
          >
            <TriangleAlertIcon className="size-3.5 shrink-0" />
            <span className="truncate">{tab.assist.error}</span>
          </span>
        ) : (
          <Kbd className="hidden sm:inline-flex">Tab</Kbd>
        )}
      </div>
      <div className="absolute right-2 bottom-2 flex items-center gap-2">
        <KbdGroup className="hidden sm:inline-flex">
          <Kbd>⌘</Kbd>
          <Kbd>↵</Kbd>
        </KbdGroup>
        <Button size="sm" onClick={run} disabled={!connector || running}>
          {running ? <Spinner /> : <PlayIcon />}
          Run
        </Button>
      </div>
    </div>
  );
}
