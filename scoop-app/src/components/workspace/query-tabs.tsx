"use client";

import { FileCode2Icon, PlusIcon, XIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { SidebarTrigger, useSidebar } from "@/components/ui/sidebar";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { newId, useWorkspace } from "@/lib/workspace/store";

import { QueryEditor } from "./query-editor";
import { ResultsGrid } from "./results-grid";
import { ResultsPagination } from "./results-pagination";

export function QueryTabs() {
  const { state, dispatch } = useWorkspace();
  const { state: sidebarState } = useSidebar();
  const openTab = () => dispatch({ type: "openTab", id: newId() });
  const closeTab = (id: string) =>
    dispatch({ type: "closeTab", id, replacementId: newId() });

  return (
    <Tabs
      value={state.activeTabId}
      onValueChange={(id) => dispatch({ type: "setActiveTab", id: String(id) })}
      className="min-h-0 flex-1 gap-0"
    >
      <div className="flex h-10 shrink-0 items-center gap-1 border-b bg-muted/40 px-1">
        {sidebarState === "collapsed" && <SidebarTrigger />}
        <div className="no-scrollbar flex min-w-0 flex-1 items-center overflow-x-auto">
          <TabsList variant="line" className="h-10 gap-0 p-0">
            {state.tabs.map((tab) => (
              <TabsTrigger
                key={tab.id}
                value={tab.id}
                nativeButton={false}
                render={<div />}
                onAuxClick={(e) => {
                  if (e.button === 1) closeTab(tab.id);
                }}
                className="group/tab h-10 max-w-48 flex-none cursor-default gap-1.5 rounded-none border-r border-r-border px-3 data-active:bg-background group-data-horizontal/tabs:after:bottom-0"
              >
                {tab.run.status === "running" ? (
                  <Spinner className="size-3.5" />
                ) : (
                  <FileCode2Icon className="size-3.5 text-muted-foreground" />
                )}
                <span className="truncate">{tab.title}</span>
                <button
                  type="button"
                  aria-label={`Close ${tab.title}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    closeTab(tab.id);
                  }}
                  className="-mr-1 ml-0.5 rounded-md p-0.5 text-muted-foreground opacity-0 group-hover/tab:opacity-100 group-data-active/tab:opacity-100 hover:bg-muted hover:text-foreground focus-visible:opacity-100"
                >
                  <XIcon className="size-3.5" />
                </button>
              </TabsTrigger>
            ))}
          </TabsList>
          <Button
            variant="ghost"
            size="icon-sm"
            className="ml-1 shrink-0"
            aria-label="New query tab"
            title="New query tab"
            onClick={openTab}
          >
            <PlusIcon />
          </Button>
        </div>
      </div>

      {/* Hidden panels unmount; each tab's text and results live in the store. */}
      {state.tabs.map((tab) => (
        <TabsContent key={tab.id} value={tab.id} className="min-h-0">
          <ResizablePanelGroup orientation="vertical">
            <ResizablePanel defaultSize="35%" minSize={80}>
              <QueryEditor tab={tab} />
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel minSize={120}>
              <div className="flex h-full min-h-0 flex-col">
                <div className="min-h-0 flex-1">
                  <ResultsGrid run={tab.run} />
                </div>
                <ResultsPagination tab={tab} />
              </div>
            </ResizablePanel>
          </ResizablePanelGroup>
        </TabsContent>
      ))}
    </Tabs>
  );
}
