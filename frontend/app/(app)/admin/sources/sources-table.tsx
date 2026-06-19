"use client";

/** AdminSourcesTable — list of sources + "Sync now" action + create dialog. */
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { RefreshCw, Trash2, Database, Plus } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { EmptyState } from "@/components/empty-state";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  sourcesApi,
  type Source,
  type SourceType,
  ApiError,
} from "@/lib/api-client";

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
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base">{t("title")}</CardTitle>
        <CreateSourceDialog onCreated={reload} />
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
                  <th className="py-2 pr-3 font-medium">
                    {tCommon("actions")}
                  </th>
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

function CreateSourceDialog({ onCreated }: { onCreated: () => void }) {
  const t = useTranslations("admin.sources");
  const tCommon = useTranslations("common");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [type, setType] = useState<SourceType>("google_drive");
  const [folderId, setFolderId] = useState("");
  const [integrationToken, setIntegrationToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const config: Record<string, unknown> = {};
    if (type === "google_drive" && folderId.trim()) {
      config.folder_id = folderId.trim();
    }
    if (type === "notion" && integrationToken.trim()) {
      config.integration_token = integrationToken.trim();
    }
    try {
      await sourcesApi.create({ name, type, config });
      setOpen(false);
      setName("");
      setFolderId("");
      setIntegrationToken("");
      setType("google_drive");
      onCreated();
    } catch (err) {
      if (err instanceof ApiError) setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm">
          <Plus className="h-4 w-4" />
          {t("newSource")}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("createTitle")}</DialogTitle>
          <DialogDescription>{t("createIntro")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-3">
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="source-name">{t("name")}</Label>
            <Input
              id="source-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="source-type">{t("type")}</Label>
            <select
              id="source-type"
              value={type}
              onChange={(e) => setType(e.target.value as SourceType)}
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <option value="google_drive">{t("typeGoogleDrive")}</option>
              <option value="notion">{t("typeNotion")}</option>
            </select>
          </div>
          {type === "google_drive" && (
            <div className="space-y-1.5">
              <Label htmlFor="source-folder-id">{t("folderId")}</Label>
              <Input
                id="source-folder-id"
                value={folderId}
                onChange={(e) => setFolderId(e.target.value)}
                placeholder={t("folderIdHint")}
              />
            </div>
          )}
          {type === "notion" && (
            <div className="space-y-1.5">
              <Label htmlFor="source-token">{t("integrationToken")}</Label>
              <Input
                id="source-token"
                type="password"
                value={integrationToken}
                onChange={(e) => setIntegrationToken(e.target.value)}
                placeholder={t("integrationTokenHint")}
                required
              />
            </div>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
            >
              {tCommon("cancel")}
            </Button>
            <Button type="submit" disabled={busy || !name.trim()}>
              {busy ? "..." : t("create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
