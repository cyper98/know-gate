"use client";

/** AdminGroupsTable — list + create + delete. */
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Plus, Trash2, FolderTree } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { groupsApi, type Group, ApiError } from "@/lib/api-client";

export function AdminGroupsTable() {
  const t = useTranslations("admin.groups");
  const tCommon = useTranslations("common");
  const [items, setItems] = useState<Group[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = () => {
    groupsApi
      .list()
      .then((p) => setItems(p.data))
      .catch((e) => {
        if (e instanceof ApiError) setError(e.message);
        setItems([]);
      });
  };
  useEffect(reload, []);

  const remove = async (g: Group) => {
    if (!window.confirm(t("deleteConfirm", { name: g.name }))) return;
    setBusy(g.id);
    try {
      await groupsApi.delete(g.id);
      reload();
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.code === "E6" || e.code === "E12") setError(t("inUseBlock"));
        else setError(e.message);
      }
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
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {items === null ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">{t("name")}</th>
                  <th className="py-2 pr-3 font-medium">{t("description")}</th>
                  <th className="py-2 pr-3 font-medium">{t("members")}</th>
                  <th className="py-2 pr-3 font-medium">{t("documents")}</th>
                  <th className="py-2 pr-3 font-medium">{tCommon("actions")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((g) => (
                  <tr key={g.id} className="border-b last:border-0">
                    <td className="py-2 pr-3">
                      <div className="flex items-center gap-2">
                        <FolderTree className="h-4 w-4 text-muted-foreground" />
                        {g.name}
                      </div>
                    </td>
                    <td className="py-2 pr-3 text-muted-foreground">
                      {g.description ?? "—"}
                    </td>
                    <td className="py-2 pr-3">
                      <Badge variant="outline">{g.member_count ?? 0}</Badge>
                    </td>
                    <td className="py-2 pr-3">
                      <Badge variant="outline">{g.document_count ?? 0}</Badge>
                    </td>
                    <td className="py-2 pr-3">
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => remove(g)}
                        disabled={busy === g.id}
                        aria-label={tCommon("delete")}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-xs text-muted-foreground">
          <Plus className="inline h-3 w-3" /> Group create + member management is a follow-up.
        </p>
      </CardContent>
    </Card>
  );
}
