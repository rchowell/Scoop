"use client";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarRail,
  SidebarTrigger,
} from "@/components/ui/sidebar";

import { ConnectorSwitcher } from "./connector-switcher";
import { SchemaTree } from "./schema-tree";

export function AppSidebar() {
  return (
    <Sidebar>
      <SidebarHeader className="border-b">
        <ConnectorSwitcher />
      </SidebarHeader>
      <SidebarContent>
        <SchemaTree />
      </SidebarContent>
      <SidebarFooter>
        <SidebarTrigger />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
