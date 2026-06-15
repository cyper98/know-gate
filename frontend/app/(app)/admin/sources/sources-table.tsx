"use client";

/** AdminSourcesTable — list of sources + "Sync now" action. */
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { RefreshCw, Trash2, Database } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/empty-state";
import { sourcesApi, type Source, ApiError } from "@/lib/api-client";

export function AdminSourcesTable() {
  const t = useTranslations("admin.sources");
  const tCommon = useTranslations("common");
  const [items, setItems] = useState<Source[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = () => {
    setError(null);
    sourcesApi
      .list()
      .then(setItems)
      .catch((e) => {
        if (e instanceof ApiError) setError(e.message);
        setItems([]);
      });
  };

  useEffect(reload, []);

  const triggerSync = async (id: string) => {
    setBusy(id);
    try {
      await sourcesApi.triggerSync(id);
    } catch (e) {
      if (e instanceof ApiError) setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const remove = async (id: string) => {
    if (!window.confirm(t("deleteConfirm"))) return;
    setBusy(id);
    try {
      await sourcesApi.delete(id);
      reload();
    } catch (e) {
      if (e instanceof ApiError) setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {error && <p className="text-sm text-destructive">{error}</p>}
        {items === null ? (
          <div className="space-y-2">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : items.length === 0 ? (
          <EmptyState
            icon={<Database className="h-8 w-8" />}
            title={tCommon("noData")}
            description="No sources configured yet."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">{t("name")}</th>
                  <th className="py-2 pr-3 font-medium">{t("type")}</th>
                  <th className="py-2 pr-3 font-medium">{t("status")}</th>
                  <th className="py-2 pr-3 font-medium">{t("lastSync")}</th>
                  <th className="py-2 pr-3 font-medium">{tCommon("actions")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((s) => (
                  <tr key={s.id} className="border-b last:border-0">
                    <td className="py-2 pr-3">{s.name}</td>
                    <td className="py-2 pr-3">
                      <Badge variant="outline">{s.type}</Badge>
                    </td>
                    <td className="py-2 pr-3">
                      <Badge
                        variant={
                          s.status === "active"
                            ? "success"
                            : s.status === "error"
                              ? "destructive"
                              : "secondary"
                        }
                      >
                        {s.status}
                      </Badge>
                    </td>
                    <td className="py-2 pr-3 text-muted-foreground">
                      {s.last_sync_at
                        ? new Date(s.last_sync_at).toLocaleString()
                        : t("lastSyncNever")}
                    </td>
                    <td className="py-2 pr-3">
                      <div className="flex items-center gap-1">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => triggerSync(s.id)}
                          disabled={busy === s.id}
                        >
                          <RefreshCw className="h-3 w-3" />
                          {t("syncNow")}
                        </Button>
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => remove(s.id)}
                          disabled={busy === s.id}
                          aria-label={tCommon("delete")}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
