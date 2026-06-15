"use client";

/** HistoryList — paginated list of the caller's past questions. */
import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/empty-state";
import { queryApi, type QueryHistoryItem, ApiError } from "@/lib/api-client";

const PAGE_SIZE = 20;

export function HistoryList() {
  const t = useTranslations("query");
  const params = useSearchParams();
  const selectedId = params.get("id");
  const [items, setItems] = useState<QueryHistoryItem[] | null>(null);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<QueryHistoryItem | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    queryApi
      .history(PAGE_SIZE, offset)
      .then((rows) => {
        if (cancelled) return;
        setItems(rows);
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof ApiError) setError(e.message);
        setItems([]);
      });
    return () => {
      cancelled = true;
    };
  }, [offset]);

  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      return;
    }
    let cancelled = false;
    queryApi
      .get(selectedId)
      .then((row) => {
        if (!cancelled) setSelected(row);
      })
      .catch(() => {
        if (!cancelled) setSelected(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  return (
    <div className="grid gap-4 md:grid-cols-[1fr_1.2fr]">
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold">{t("historyTitle")}</h1>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              aria-label="Previous page"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              disabled={items !== null && items.length < PAGE_SIZE}
              onClick={() => setOffset(offset + PAGE_SIZE)}
              aria-label="Next page"
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
        {items === null ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <EmptyState title={t("historyEmpty")} />
        ) : (
          <ul className="space-y-2">
            {items.map((q) => (
              <li key={q.id}>
                <Link href={`/query/history?id=${encodeURIComponent(q.id)}`}>
                  <Card
                    className={
                      selectedId === q.id
                        ? "border-primary"
                        : "hover:border-primary/50 transition-colors"
                    }
                  >
                    <CardContent className="p-3">
                      <p className="line-clamp-2 text-sm font-medium">{q.query_text}</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {new Date(q.created_at).toLocaleString()} · {q.status}
                      </p>
                    </CardContent>
                  </Card>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        {selected ? (
          <Card>
            <CardContent className="space-y-3 p-6">
              <h2 className="text-lg font-semibold">{selected.query_text}</h2>
              <p className="text-xs text-muted-foreground">
                {new Date(selected.created_at).toLocaleString()}
              </p>
              {selected.answer_text ? (
                <p className="whitespace-pre-wrap text-sm leading-relaxed">
                  {selected.answer_text}
                </p>
              ) : (
                <p className="text-sm italic text-muted-foreground">—</p>
              )}
            </CardContent>
          </Card>
        ) : (
          <EmptyState title={t("viewAnswer")} />
        )}
      </div>
    </div>
  );
}
