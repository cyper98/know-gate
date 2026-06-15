"use client";

/** AdminRolesTable — list + create + edit + delete. */
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Plus, Trash2, Shield } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { rolesApi, type Role, ApiError } from "@/lib/api-client";

export function AdminRolesTable() {
  const t = useTranslations("admin.roles");
  const tCommon = useTranslations("common");
  const [items, setItems] = useState<Role[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = () => {
    rolesApi
      .list()
      .then((p) => setItems(p.data))
      .catch((e) => {
        if (e instanceof ApiError) setError(e.message);
        setItems([]);
      });
  };
  useEffect(reload, []);

  const remove = async (r: Role) => {
    if (!window.confirm(t("deleteConfirm", { name: r.name }))) return;
    setBusy(r.id);
    try {
      await rolesApi.delete(r.id);
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
                  <th className="py-2 pr-3 font-medium">{t("permissions")}</th>
                  <th className="py-2 pr-3 font-medium">{tCommon("actions")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((r) => (
                  <tr key={r.id} className="border-b last:border-0">
                    <td className="py-2 pr-3">
                      <div className="flex items-center gap-2">
                        <Shield className="h-4 w-4 text-muted-foreground" />
                        {r.name}
                        {r.is_static && (
                          <Badge variant="secondary" className="text-[10px]">
                            built-in
                          </Badge>
                        )}
                      </div>
                    </td>
                    <td className="py-2 pr-3">
                      <div className="flex flex-wrap gap-1">
                        {r.permissions.slice(0, 4).map((p) => (
                          <Badge key={p} variant="outline" className="text-[10px]">
                            {p}
                          </Badge>
                        ))}
                        {r.permissions.length > 4 && (
                          <span className="text-xs text-muted-foreground">
                            +{r.permissions.length - 4}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="py-2 pr-3">
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => remove(r)}
                        disabled={busy === r.id || r.is_static}
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
          <Plus className="inline h-3 w-3" /> Custom role creation is a follow-up.
        </p>
      </CardContent>
    </Card>
  );
}
