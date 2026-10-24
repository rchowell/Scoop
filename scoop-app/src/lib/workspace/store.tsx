"use client";

import * as React from "react";

import type { ExecuteResult } from "@/lib/api";

export const PAGE_SIZES = [50, 100, 250, 500] as const;
const DEFAULT_PAGE_SIZE = 100;
const STORAGE_KEY = "scoop.workspace.v1";

export type RunState = {
  status: "idle" | "running" | "done" | "error";
  /** Identifies the latest run so a slow, superseded run can't overwrite it. */
  runId?: string;
  result?: ExecuteResult;
  error?: Error;
  elapsedMs?: number;
  /** 0-based page into the result rows. */
  page: number;
  pageSize: number;
};

/** The query assistant authoring a query for a tab; never persisted. */
export type AssistState = {
  status: "idle" | "running" | "error";
  /** Identifies the latest request so a superseded one can't report into it. */
  runId?: string;
  /** The latest progress message, e.g. "Reading main.trips…". */
  step?: string;
  error?: string;
};

export type Tab = {
  id: string;
  title: string;
  connectorId: string | null;
  /** The editor's text: a query AST as JSON, or a request for the assistant. */
  text: string;
  run: RunState;
  assist: AssistState;
};

export type WorkspaceState = {
  activeConnectorId: string | null;
  tabs: Tab[];
  activeTabId: string;
  /** Next number for an untitled "Query N" tab. */
  nextQueryNumber: number;
};

type Action =
  | { type: "openTab"; id: string; title?: string; text?: string }
  | { type: "closeTab"; id: string; replacementId: string }
  | { type: "setActiveTab"; id: string }
  | { type: "setText"; id: string; text: string }
  | { type: "setConnector"; connectorId: string }
  | { type: "runStarted"; id: string; runId: string }
  /** The editor's text couldn't be run at all; shown like a failed run. */
  | { type: "runRejected"; id: string; error: Error }
  | {
      type: "runSucceeded";
      id: string;
      runId: string;
      result: ExecuteResult;
      elapsedMs: number;
    }
  | {
      type: "runFailed";
      id: string;
      runId: string;
      error: Error;
      elapsedMs: number;
    }
  | { type: "assistStarted"; id: string; runId: string }
  | { type: "assistStep"; id: string; runId: string; step: string }
  | { type: "assistFinished"; id: string; runId: string }
  | { type: "assistFailed"; id: string; runId: string; error: string }
  | { type: "setPage"; id: string; page: number }
  | { type: "setPageSize"; id: string; pageSize: number };

const idleRun = (pageSize = DEFAULT_PAGE_SIZE): RunState => ({
  status: "idle",
  page: 0,
  pageSize,
});

const idleAssist: AssistState = { status: "idle" };

export const newId = () => crypto.randomUUID();

function newTab(
  state: Pick<WorkspaceState, "activeConnectorId" | "nextQueryNumber">,
  id: string,
  title?: string,
  text = "",
): Tab {
  return {
    id,
    title: title ?? `Query ${state.nextQueryNumber}`,
    connectorId: state.activeConnectorId,
    text,
    run: idleRun(),
    assist: idleAssist,
  };
}

function updateTab(
  state: WorkspaceState,
  id: string,
  update: (tab: Tab) => Tab,
): WorkspaceState {
  return {
    ...state,
    tabs: state.tabs.map((tab) => (tab.id === id ? update(tab) : tab)),
  };
}

function reducer(state: WorkspaceState, action: Action): WorkspaceState {
  switch (action.type) {
    case "openTab": {
      const tab = newTab(state, action.id, action.title, action.text);
      return {
        ...state,
        tabs: [...state.tabs, tab],
        activeTabId: tab.id,
        nextQueryNumber: state.nextQueryNumber + (action.title ? 0 : 1),
      };
    }
    case "closeTab": {
      const index = state.tabs.findIndex((t) => t.id === action.id);
      if (index === -1) return state;
      const tabs = state.tabs.filter((t) => t.id !== action.id);
      if (tabs.length === 0) {
        // Always keep one tab open.
        const tab = newTab(
          { ...state, nextQueryNumber: 1 },
          action.replacementId,
        );
        return {
          ...state,
          tabs: [tab],
          activeTabId: tab.id,
          nextQueryNumber: 2,
        };
      }
      if (state.activeTabId !== action.id) return { ...state, tabs };
      const next = tabs[Math.min(index, tabs.length - 1)];
      return {
        ...state,
        tabs,
        activeTabId: next.id,
        activeConnectorId: next.connectorId ?? state.activeConnectorId,
      };
    }
    case "setActiveTab": {
      const tab = state.tabs.find((t) => t.id === action.id);
      if (!tab) return state;
      // The connector switcher follows the active tab.
      return {
        ...state,
        activeTabId: tab.id,
        activeConnectorId: tab.connectorId ?? state.activeConnectorId,
      };
    }
    case "setText":
      return updateTab(state, action.id, (tab) => ({
        ...tab,
        text: action.text,
        // Editing dismisses a failed generation's message.
        assist: tab.assist.status === "error" ? idleAssist : tab.assist,
      }));
    case "setConnector":
      // Switching connectors rebinds the active tab.
      return updateTab(
        { ...state, activeConnectorId: action.connectorId },
        state.activeTabId,
        (tab) => ({ ...tab, connectorId: action.connectorId }),
      );
    case "runStarted":
      return updateTab(state, action.id, (tab) => ({
        ...tab,
        run: {
          ...idleRun(tab.run.pageSize),
          status: "running",
          runId: action.runId,
        },
      }));
    case "runRejected":
      return updateTab(state, action.id, (tab) => ({
        ...tab,
        run: {
          ...idleRun(tab.run.pageSize),
          status: "error",
          error: action.error,
          elapsedMs: 0,
        },
      }));
    case "runSucceeded":
      return updateTab(state, action.id, (tab) =>
        tab.run.runId !== action.runId
          ? tab
          : {
              ...tab,
              run: {
                ...tab.run,
                status: "done",
                result: action.result,
                elapsedMs: action.elapsedMs,
                page: 0,
              },
            },
      );
    case "runFailed":
      return updateTab(state, action.id, (tab) =>
        tab.run.runId !== action.runId
          ? tab
          : {
              ...tab,
              run: {
                ...tab.run,
                status: "error",
                error: action.error,
                elapsedMs: action.elapsedMs,
              },
            },
      );
    case "assistStarted":
      return updateTab(state, action.id, (tab) => ({
        ...tab,
        assist: { status: "running", runId: action.runId },
      }));
    case "assistStep":
      return updateTab(state, action.id, (tab) =>
        tab.assist.runId !== action.runId
          ? tab
          : { ...tab, assist: { ...tab.assist, step: action.step } },
      );
    case "assistFinished":
      return updateTab(state, action.id, (tab) =>
        tab.assist.runId !== action.runId
          ? tab
          : { ...tab, assist: idleAssist },
      );
    case "assistFailed":
      return updateTab(state, action.id, (tab) =>
        tab.assist.runId !== action.runId
          ? tab
          : {
              ...tab,
              assist: {
                status: "error",
                runId: action.runId,
                error: action.error,
              },
            },
      );
    case "setPage":
      return updateTab(state, action.id, (tab) => ({
        ...tab,
        run: { ...tab.run, page: action.page },
      }));
    case "setPageSize":
      return updateTab(state, action.id, (tab) => ({
        ...tab,
        // Keep the first visible row on screen after resizing.
        run: {
          ...tab.run,
          pageSize: action.pageSize,
          page: Math.floor((tab.run.page * tab.run.pageSize) / action.pageSize),
        },
      }));
  }
}

// ============================================================================
// Persistence
// ============================================================================

type PersistedState = {
  activeConnectorId: string | null;
  activeTabId: string;
  nextQueryNumber: number;
  tabs: {
    id: string;
    title: string;
    connectorId: string | null;
    text: string;
    /** Saved by versions that edited SQL; restored as the tab's text. */
    sql?: string;
  }[];
};

function initialState(): WorkspaceState {
  const fallback = (): WorkspaceState => {
    const tab = newTab(
      { activeConnectorId: null, nextQueryNumber: 1 },
      newId(),
    );
    return {
      activeConnectorId: null,
      tabs: [tab],
      activeTabId: tab.id,
      nextQueryNumber: 2,
    };
  };

  let saved: PersistedState | null = null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    saved = raw ? (JSON.parse(raw) as PersistedState) : null;
  } catch {
    return fallback();
  }
  if (!saved || !Array.isArray(saved.tabs) || saved.tabs.length === 0) {
    return fallback();
  }

  const tabs: Tab[] = saved.tabs.map((t) => ({
    id: String(t.id),
    title: String(t.title),
    connectorId: t.connectorId ?? null,
    text: String(t.text ?? t.sql ?? ""),
    run: idleRun(),
    assist: idleAssist,
  }));
  const activeTabId = tabs.some((t) => t.id === saved.activeTabId)
    ? saved.activeTabId
    : tabs[0].id;
  return {
    activeConnectorId: saved.activeConnectorId ?? null,
    tabs,
    activeTabId,
    nextQueryNumber: Number(saved.nextQueryNumber) || tabs.length + 1,
  };
}

function persist(state: WorkspaceState) {
  const saved: PersistedState = {
    activeConnectorId: state.activeConnectorId,
    activeTabId: state.activeTabId,
    nextQueryNumber: state.nextQueryNumber,
    tabs: state.tabs.map(({ id, title, connectorId, text }) => ({
      id,
      title,
      connectorId,
      text,
    })),
  };
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(saved));
  } catch {
    // Storage may be full or blocked; the workspace still works in memory.
  }
}

// ============================================================================
// Context
// ============================================================================

type WorkspaceContextValue = {
  state: WorkspaceState;
  dispatch: React.Dispatch<Action>;
};

const WorkspaceContext = React.createContext<WorkspaceContextValue | null>(
  null,
);

/**
 * Holds tabs and query results. Must only render on the client: the initial
 * state is read from localStorage (see `ClientOnly` in the app shell).
 */
export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = React.useReducer(reducer, undefined, initialState);

  React.useEffect(() => {
    const timeout = window.setTimeout(() => persist(state), 300);
    return () => window.clearTimeout(timeout);
  }, [state]);

  const value = React.useMemo(() => ({ state, dispatch }), [state]);
  return (
    <WorkspaceContext.Provider value={value}>
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace() {
  const context = React.useContext(WorkspaceContext);
  if (!context) {
    throw new Error("useWorkspace must be used within a WorkspaceProvider.");
  }
  return context;
}

export function useActiveTab(): Tab {
  const { state } = useWorkspace();
  return state.tabs.find((t) => t.id === state.activeTabId) ?? state.tabs[0];
}
