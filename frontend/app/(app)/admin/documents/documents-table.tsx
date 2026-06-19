"use client";

/** AdminDocumentsTable — list, filter, delete, preview documents. */
import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Trash2, ExternalLink, FileText, Search } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { EmptyState } from "@/components/empty-state";
import { documentsApi, type Document, ApiError } from "@/lib/api-client";

const SELECT_CLASS =
  "flex h-9 rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";

export function AdminDocumentsTable() {
  const t = useTranslations("admin.documents");
  const tCommon = useTranslations("common");
  const [items, setItems] = useState<Document[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [titleFilter, setTitleFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [languageFilter, setLanguageFilter] = useState("");

  const reload = useCallback(() => {
    setError(null);
    documentsApi
      .list({
        title_contains: titleFilter || undefined,
        status: statusFilter || undefined,
        source: sourceFilter || undefined,
        language: languageFilter || undefined,
        limit: 50,
      })
      .then((page) => setItems(page.data))
      .catch((e) => {
        if (e instanceof ApiError) setError(e.message);
        setItems([]);
      });
  }, [titleFilter, statusFilter, sourceFilter, languageFilter]);

  useEffect(reload, [reload]);

  const remove = async (doc: Document) => {
    if (!window.confirm(t("deleteConfirm"))) return;
    setBusy(doc.id);
    try {
      await documentsApi.delete(doc.id);
      reload();
    } catch (e) {
      if (e instanceof ApiError) setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const preview = async (id: string) => {
    setBusy(id);
    try {
      const p = await documentsApi.preview(id);
      window.open(p.url, "_blank");
    } catch (e) {
      if (e instanceof ApiError) setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const statusVariant = (s: string) => {
    switch (s) {
      case "active":
        return "success";
      case "indexing":
        return "secondary";
      case "outdated":
      case "deprecated":
        return "outline";
      case "deleted":
      case "archived":
        return "destructive";
      default:
        return "secondary";
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
        {/* Filters */}
        <div className="flex flex-wrap gap-2">
          <div className="relative flex-1 min-w-[180px]">
            <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={titleFilter}
              onChange={(e) => setTitleFilter(e.target.value)}
              placeholder={t("filterTitle")}
              className="pl-8"
            />
          </div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className={SELECT_CLASS}
          >
            <option value="">{t("filterStatus")}</option>
            <option value="active">active</option>
            <option value="indexing">indexing</option>
            <option value="outdated">outdated</option>
            <option value="deprecated">deprecated</option>
            <option value="archived">archived</option>
            <option value="deleted">deleted</option>
          </select>
          <select
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
            className={SELECT_CLASS}
          >
            <option value="">{t("filterSource")}</option>
            <option value="google_drive">google_drive</option>
            <option value="notion">notion</option>
          </select>
          <select
            value={languageFilter}
            onChange={(e) => setLanguageFilter(e.target.value)}
            className={SELECT_CLASS}
          >
            <option value="">{t("filterLanguage")}</option>
            <option value="en">en</option>
            <option value="vi">vi</option>
          </select>
        </div>

        {items === null ? (
          <div className="space-y-2">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : items.length === 0 ? (
          <EmptyState
            icon={<FileText className="h-8 w-8" />}
            title={tCommon("noData")}
            description={t("noDocs")}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">{t("docTitle")}</th>
                  <th className="py-2 pr-3 font-medium">{t("source")}</th>
                  <th className="py-2 pr-3 font-medium">{t("status")}</th>
                  <th className="py-2 pr-3 font-medium">{t("language")}</th>
                  <th className="py-2 pr-3 font-medium">{t("owner")}</th>
                  <th className="py-2 pr-3 font-medium">{t("updatedAt")}</th>
                  <th className="py-2 pr-3 font-medium">
                    {tCommon("actions")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((doc) => (
                  <tr key={doc.id} className="border-b last:border-0">
                    <td
                      className="py-2 pr-3 max-w-[220px] truncate"
                      title={doc.title}
                    >
                      {doc.title}
                    </td>
                    <td className="py-2 pr-3">
                      <Badge variant="outline">{doc.source}</Badge>
                    </td>
                    <td className="py-2 pr-3">
                      <Badge variant={statusVariant(doc.status)}>
                        {doc.status}
                      </Badge>
                    </td>
                    <td className="py-2 pr-3 text-muted-foreground">
                      {doc.language ?? "\u2014"}
                    </td>
                    <td className="py-2 pr-3 text-muted-foreground">
                      {doc.owner ?? "\u2014"}
                    </td>
                    <td className="py-2 pr-3 text-muted-foreground text-xs">
                      {new Date(doc.updated_at).toLocaleString()}
                    </td>
                    <td className="py-2 pr-3">
                      <div className="flex items-center gap-1">
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => preview(doc.id)}
                          disabled={busy === doc.id}
                          aria-label={t("preview")}
                          title={t("preview")}
                        >
                          <ExternalLink className="h-4 w-4" />
                        </Button>
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => remove(doc)}
                          disabled={busy === doc.id}
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
