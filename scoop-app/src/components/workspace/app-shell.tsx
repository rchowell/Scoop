"use client";

import * as React from "react";

import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { Spinner } from "@/components/ui/spinner";
import { WorkspaceProvider } from "@/lib/workspace/store";

import { AppSidebar } from "./app-sidebar";
import { QueryTabs } from "./query-tabs";

const subscribe = () => () => {};

/** True only after hydration, so client-only state can be read safely. */
function useIsClient() {
  return React.useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
}

export function AppShell() {
  const isClient = useIsClient();

  // The workspace restores from localStorage, which the server can't see.
  if (!isClient) {
    return (
      <div className="flex h-svh items-center justify-center text-muted-foreground">
        <Spinner />
      </div>
    );
  }

  return (
    <WorkspaceProvider>
      <SidebarProvider className="h-svh min-h-0">
        <AppSidebar />
        <SidebarInset className="min-h-0 min-w-0 overflow-hidden">
          <QueryTabs />
        </SidebarInset>
      </SidebarProvider>
    </WorkspaceProvider>
  );
}
