"use client";

/** AppShell — sidebar + topbar layout used by every page in (app). */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  LayoutDashboard,
  Search,
  History,
  Database,
  FileText,
  Users,
  Shield,
  FolderTree,
  Settings as SettingsIcon,
  ScrollText,
  LogOut,
} from "lucide-react";

import { useUser } from "@/components/user-provider";
import { LangSwitcher } from "@/components/lang-switcher";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { logoutAction } from "@/lib/auth-actions";

interface NavItem {
  href: string;
  labelKey:
    | "dashboard"
    | "query"
    | "history"
    | "sources"
    | "documents"
    | "users"
    | "roles"
    | "groups"
    | "settings"
    | "auditLog";
  icon: React.ComponentType<{ className?: string }>;
  /** Restrict to these roles. Empty = visible to everyone signed in. */
  roles?: string[];
}

const NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", labelKey: "dashboard", icon: LayoutDashboard },
  { href: "/query", labelKey: "query", icon: Search },
  { href: "/query/history", labelKey: "history", icon: History },
  {
    href: "/admin/sources",
    labelKey: "sources",
    icon: Database,
    roles: ["admin"],
  },
  {
    href: "/admin/documents",
    labelKey: "documents",
    icon: FileText,
    roles: ["admin"],
  },
  { href: "/admin/users", labelKey: "users", icon: Users, roles: ["admin"] },
  { href: "/admin/roles", labelKey: "roles", icon: Shield, roles: ["admin"] },
  {
    href: "/admin/groups",
    labelKey: "groups",
    icon: FolderTree,
    roles: ["admin"],
  },
  {
    href: "/admin/settings",
    labelKey: "settings",
    icon: SettingsIcon,
    roles: ["admin"],
  },
  {
    href: "/admin/audit-log",
    labelKey: "auditLog",
    icon: ScrollText,
    roles: ["admin"],
  },
];

interface Props {
  children: React.ReactNode;
}

export function AppShell({ children }: Props) {
  const t = useTranslations("nav");
  const tCommon = useTranslations("common");
  const pathname = usePathname();
  const { user } = useUser();

  return (
    <div className="grid min-h-screen grid-cols-1 md:grid-cols-[220px_1fr]">
      <aside className="hidden border-r bg-muted/30 md:flex md:flex-col">
        <div className="flex h-14 items-center border-b px-4 font-semibold">
          KnowGate
        </div>
        <nav className="flex-1 space-y-1 p-2">
          {NAV_ITEMS.map((item) => {
            if (
              item.roles &&
              (!user || !user.roles.some((r) => item.roles!.includes(r)))
            ) {
              return null;
            }
            const Icon = item.icon;
            const active =
              pathname === item.href ||
              (pathname.startsWith(`${item.href}/`) &&
                !NAV_ITEMS.some(
                  (other) =>
                    other.href !== item.href &&
                    other.href.startsWith(`${item.href}/`) &&
                    (pathname === other.href ||
                      pathname.startsWith(`${other.href}/`)),
                ));
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                )}
              >
                <Icon className="h-4 w-4" />
                {t(item.labelKey)}
              </Link>
            );
          })}
        </nav>
        <div className="border-t p-2">
          <form action={logoutAction}>
            <Button
              variant="ghost"
              className="w-full justify-start"
              type="submit"
            >
              <LogOut className="mr-2 h-4 w-4" />
              {t("logout")}
            </Button>
          </form>
        </div>
      </aside>
      <div className="flex flex-col">
        <header className="flex h-14 items-center justify-between border-b bg-background px-4">
          <div className="md:hidden font-semibold">KnowGate</div>
          <div className="ml-auto flex items-center gap-3">
            <LangSwitcher />
            {user && (
              <div className="hidden text-sm text-muted-foreground md:block">
                {user.display_name} · {tCommon("language")}:{" "}
                {user.language_pref ?? "en"}
              </div>
            )}
          </div>
        </header>
        <main className="flex-1 overflow-y-auto bg-background p-4 md:p-6">
          {children}
        </main>
      </div>
    </div>
  );
}
