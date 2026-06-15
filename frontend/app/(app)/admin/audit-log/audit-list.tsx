"use client";

/** AdminAuditList — paginated audit log. */
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/empty-state";
import { settingsApi, type AuditLogEntry, ApiError } from "@/lib/api-client";

const PAGE_SIZE = 50;

export function AdminAuditList() {
  const t = useTranslations("admin.audit");
  const tCommon = useTranslations("common");
  const [items, setItems] = useState<AuditLogEntry[] | null>(null);
  const [cursor, setCursor] = useState<string | undefined>(undefined);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [stack, setStack] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    settingsApi
      .auditLog({ limit: PAGE_SIZE, cursor })
      .then((page) => {
        if (cancelled) return;
        setItems(page.data);
        setNextCursor(page.meta?.next_cursor ?? null);
        setStack((s) => (cursor ? [...s, cursor] : s));
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof ApiError) setError(e.message);
        setItems([]);
        setNextCursor(null);
      });
    return () => {
      cancelled = true;
    };
  }, [cursor]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {error && <p className="text-sm text-destructive">{error}</p>}
        {items === null ? (
          <Skeleton className="h-32 w-full" />
        ) : items.length === 0 ? (
          <EmptyState title={tCommon("noData")} />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th className="py-2 pr-3 font-medium">{t("at")}</th>
                    <th className="py-2 pr-3 font-medium">{t("actor")}</th>
                    <th className="py-2 pr-3 font-medium">{t("action")}</th>
                    <th className="py-2 pr-3 font-medium">{t("target")}</th>
                    <th className="py-2 pr-3 font-medium">{t("ip")}</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((it) => (
                    <tr key={it.id} className="border-b last:border-0">
                      <td className="py-2 pr-3 text-muted-foreground">
                        {new Date(it.created_at).toLocaleString()}
                      </td>
                      <td className="py-2 pr-3">{it.actor_email ?? it.actor_id}</td>
                      <td className="py-2 pr-3 font-mono text-xs">{it.action}</td>
                      <td className="py-2 pr-3 text-muted-foreground">
                        {it.target_type ? `${it.target_type}:${it.target_id ?? ""}` : "—"}
                      </td>
                      <td className="py-2 pr-3 text-muted-foreground">
                        {it.ip_address ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex justify-end gap-1">
              <Button
                size="icon"
                variant="ghost"
                disabled={stack.length === 0}
                onClick={() => {
                  const prev = stack[stack.length - 1];
                  setStack((s) => s.slice(0, -1));
                  setCursor(prev);
                }}
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                disabled={!nextCursor}
                onClick={() => setCursor(nextCursor ?? undefined)}
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
