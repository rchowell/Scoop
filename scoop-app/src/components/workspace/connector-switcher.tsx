"use client";

import {
  CheckIcon,
  ChevronsUpDownIcon,
  DatabaseIcon,
  RefreshCwIcon,
  Settings2Icon,
  TriangleAlertIcon,
} from "lucide-react";
import * as React from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSkeleton,
} from "@/components/ui/sidebar";
import { useConnectorKinds, type ConnectorKind } from "@/lib/api";
import {
  useActiveConnector,
  useConnectorList,
} from "@/lib/workspace/use-active-connector";
import { useWorkspace } from "@/lib/workspace/store";

import { ConnectorConfigDialog } from "./connector-config-dialog";

export function ConnectorSwitcher() {
  const { dispatch } = useWorkspace();
  const { connector, connectors, isLoading, error } = useActiveConnector();
  const { mutate } = useConnectorList();
  const { data: kinds } = useConnectorKinds();
  const kindName = (kind: ConnectorKind) =>
    kinds?.kinds.find((k) => k.kind === kind)?.name ?? kind;
  // Bumped on each open so the dialog starts fresh on the active connector.
  const [configKey, setConfigKey] = React.useState(0);
  const [configOpen, setConfigOpen] = React.useState(false);
  const openConfig = () => {
    setConfigKey((k) => k + 1);
    setConfigOpen(true);
  };

  if (isLoading) {
    return <SidebarMenuSkeleton showIcon className="h-12" />;
  }

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <SidebarMenuButton
                size="lg"
                className="data-popup-open:bg-sidebar-accent data-popup-open:text-sidebar-accent-foreground"
              />
            }
          >
            <div className="flex aspect-square size-8 items-center justify-center rounded-md bg-sidebar-primary text-sidebar-primary-foreground">
              {error ? <TriangleAlertIcon /> : <DatabaseIcon />}
            </div>
            <div className="grid flex-1 text-left text-sm leading-tight">
              <span className="truncate font-medium">
                {error
                  ? "API unreachable"
                  : (connector?.name ?? "No connectors")}
              </span>
              <span className="truncate text-xs text-muted-foreground">
                {error
                  ? error.message
                  : connector
                    ? kindName(connector.kind)
                    : "Configure connectors to start"}
              </span>
            </div>
            <ChevronsUpDownIcon className="ml-auto" />
          </DropdownMenuTrigger>
          <DropdownMenuContent className="min-w-56" align="start">
            <DropdownMenuGroup>
              <DropdownMenuLabel>Connectors</DropdownMenuLabel>
              {connectors.map((c) => (
                <DropdownMenuItem
                  key={c.id}
                  onClick={() =>
                    dispatch({ type: "setConnector", connectorId: c.id })
                  }
                >
                  <DatabaseIcon className="text-muted-foreground" />
                  <span className="truncate">{c.name}</span>
                  <span className="ml-auto text-xs text-muted-foreground">
                    {kindName(c.kind)}
                  </span>
                  <CheckIcon
                    className={
                      c.id === connector?.id ? "opacity-100" : "opacity-0"
                    }
                  />
                </DropdownMenuItem>
              ))}
              {connectors.length === 0 && (
                <DropdownMenuItem disabled>No connectors</DropdownMenuItem>
              )}
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={openConfig}>
              <Settings2Icon />
              Configure connectors…
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => mutate()}>
              <RefreshCwIcon />
              Refresh list
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <ConnectorConfigDialog
          key={configKey}
          open={configOpen}
          onOpenChange={setConfigOpen}
          initialSelection={connector?.id ?? null}
        />
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
