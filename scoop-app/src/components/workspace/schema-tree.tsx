"use client";

import * as React from "react";
import {
  ChevronRightIcon,
  ColumnsIcon,
  CopyIcon,
  EyeIcon,
  FolderIcon,
  HashIcon,
  PlayIcon,
  RefreshCwIcon,
  SearchIcon,
  TableIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import {
  SidebarGroup,
  SidebarGroupAction,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarInput,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSkeleton,
  SidebarMenuSub,
  SidebarMenuSubItem,
} from "@/components/ui/sidebar";
import {
  useConnectorTable,
  useConnectorTables,
  type Connector,
  type Query,
} from "@/lib/api";
import { useActiveConnector } from "@/lib/workspace/use-active-connector";
import {
  countRows,
  formatQuery,
  qualifiedName,
  selectAll,
} from "@/lib/workspace/query";
import { useRunQuery } from "@/lib/workspace/use-run-query";
import { newId, useWorkspace } from "@/lib/workspace/store";

type SchemaNode = { key: string; namespace: string[]; tables: string[][] };

/** Groups table paths by namespace (every element but the last). */
function groupBySchema(paths: string[][], filter: string): SchemaNode[] {
  const needle = filter.trim().toLowerCase();
  const groups = new Map<string, SchemaNode>();
  for (const path of paths) {
    const name = path[path.length - 1] ?? "";
    if (needle && !name.toLowerCase().includes(needle)) continue;
    const namespace = path.slice(0, -1);
    const key = namespace.join(".");
    let group = groups.get(key);
    if (!group) {
      group = { key, namespace, tables: [] };
      groups.set(key, group);
    }
    group.tables.push(path);
  }
  for (const group of groups.values()) {
    group.tables.sort((a, b) => a[a.length - 1].localeCompare(b[b.length - 1]));
  }
  return [...groups.values()].sort((a, b) => a.key.localeCompare(b.key));
}

export function SchemaTree() {
  const { connector } = useActiveConnector();
  const [filter, setFilter] = React.useState("");
  const { data, error, isLoading, mutate } = useConnectorTables(connector?.id);

  const schemas = React.useMemo(
    () => groupBySchema(data?.tables ?? [], filter),
    [data, filter],
  );

  if (!connector) return null;

  return (
    <SidebarGroup>
      <SidebarGroupLabel>Schemas</SidebarGroupLabel>
      <SidebarGroupAction title="Refresh" onClick={() => mutate()}>
        <RefreshCwIcon />
        <span className="sr-only">Refresh</span>
      </SidebarGroupAction>
      <SidebarGroupContent className="flex flex-col gap-2">
        <div className="relative">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-2 size-4 -translate-y-1/2 text-muted-foreground" />
          <SidebarInput
            placeholder="Filter tables"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="pl-8"
          />
        </div>
        {isLoading ? (
          <SidebarMenu>
            {Array.from({ length: 5 }, (_, i) => (
              <SidebarMenuItem key={i}>
                <SidebarMenuSkeleton showIcon />
              </SidebarMenuItem>
            ))}
          </SidebarMenu>
        ) : error ? (
          <div className="flex flex-col gap-2 rounded-md border border-destructive/30 p-2 text-xs text-destructive">
            <span>{error.message}</span>
            <Button size="xs" variant="outline" onClick={() => mutate()}>
              Retry
            </Button>
          </div>
        ) : schemas.length === 0 ? (
          <p className="px-2 text-xs text-muted-foreground">
            {filter ? "No matching tables" : "No tables"}
          </p>
        ) : (
          <SidebarMenu>
            {schemas.map((schema) =>
              schema.namespace.length === 0 ? (
                schema.tables.map((path) => (
                  <SidebarMenuItem key={path.join(".")}>
                    <TableNode connector={connector} path={path} />
                  </SidebarMenuItem>
                ))
              ) : (
                <SchemaNodeItem
                  key={schema.key}
                  connector={connector}
                  schema={schema}
                  // Open everything while filtering so matches are visible.
                  forceOpen={filter.trim() !== ""}
                  defaultOpen={schemas.length === 1}
                />
              ),
            )}
          </SidebarMenu>
        )}
      </SidebarGroupContent>
    </SidebarGroup>
  );
}

function SchemaNodeItem({
  connector,
  schema,
  forceOpen,
  defaultOpen,
}: {
  connector: Connector;
  schema: SchemaNode;
  forceOpen: boolean;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = React.useState(defaultOpen);
  return (
    <Collapsible
      open={open || forceOpen}
      onOpenChange={setOpen}
      render={<SidebarMenuItem />}
    >
      <CollapsibleTrigger render={<SidebarMenuButton />}>
        <ChevronRightIcon className="transition-transform group-data-panel-open/menu-button:rotate-90" />
        <FolderIcon className="text-muted-foreground" />
        <span>{schema.key}</span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <SidebarMenuSub className="mr-0 pr-0">
          {schema.tables.map((path) => (
            <SidebarMenuSubItem key={path.join(".")}>
              <TableNode connector={connector} path={path} />
            </SidebarMenuSubItem>
          ))}
        </SidebarMenuSub>
      </CollapsibleContent>
    </Collapsible>
  );
}

function TableNode({
  connector,
  path,
}: {
  connector: Connector;
  path: string[];
}) {
  const [open, setOpen] = React.useState(false);
  const { dispatch } = useWorkspace();
  const runQuery = useRunQuery();
  const name = path[path.length - 1];
  const qualified = qualifiedName(path, connector.kind);

  // Only fetched once expanded; reused for the view/table icon afterwards.
  const { data: detail } = useConnectorTable(connector.id, open ? path : null);
  const Icon = detail?.kind === "view" ? EyeIcon : TableIcon;

  const openQuery = (query: Query, run: boolean) => {
    const id = newId();
    dispatch({ type: "openTab", id, title: name, text: formatQuery(query) });
    if (run) void runQuery(id, connector.id, query);
  };

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <ContextMenu>
        <ContextMenuTrigger
          render={
            <CollapsibleTrigger
              render={<SidebarMenuButton size="sm" title={path.join(".")} />}
              onDoubleClick={() => openQuery(selectAll(path, 100), true)}
            />
          }
        >
          <ChevronRightIcon className="transition-transform group-data-panel-open/menu-button:rotate-90" />
          <Icon className="text-muted-foreground" />
          <span>{name}</span>
        </ContextMenuTrigger>
        <ContextMenuContent>
          <ContextMenuItem
            onClick={() => openQuery(selectAll(path, 100), true)}
          >
            <PlayIcon />
            Select top 100 rows
          </ContextMenuItem>
          <ContextMenuItem onClick={() => openQuery(countRows(path), true)}>
            <HashIcon />
            Count rows
          </ContextMenuItem>
          <ContextMenuItem onClick={() => openQuery(selectAll(path), false)}>
            <TableIcon />
            New query on table
          </ContextMenuItem>
          <ContextMenuSeparator />
          <ContextMenuItem
            onClick={() => void navigator.clipboard?.writeText(qualified)}
          >
            <CopyIcon />
            Copy qualified name
          </ContextMenuItem>
        </ContextMenuContent>
      </ContextMenu>
      <CollapsibleContent>
        <TableColumns connectorId={connector.id} path={path} />
      </CollapsibleContent>
    </Collapsible>
  );
}

function TableColumns({
  connectorId,
  path,
}: {
  connectorId: string;
  path: string[];
}) {
  const { data, error, isLoading } = useConnectorTable(connectorId, path);

  if (isLoading) return <SidebarMenuSkeleton className="ml-6 h-6" />;
  if (error) {
    return (
      <p className="ml-7 py-1 text-xs text-destructive">{error.message}</p>
    );
  }
  return (
    <ul className="ml-4 flex flex-col border-l border-sidebar-border py-0.5 pl-2">
      {data?.columns.map((column) => (
        <li
          key={column.name}
          className="flex h-6 min-w-0 items-center gap-1.5 px-1 text-xs"
          title={`${column.name} ${column.type ?? ""}${column.nullable === false ? " NOT NULL" : ""}`}
        >
          <ColumnsIcon className="size-3 shrink-0 text-muted-foreground" />
          <span className="truncate">{column.name}</span>
          <span className="ml-auto shrink-0 font-mono text-[0.7rem] text-muted-foreground">
            {column.type?.toLowerCase()}
          </span>
        </li>
      ))}
    </ul>
  );
}
