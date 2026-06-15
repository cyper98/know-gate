"use client";

/** DashboardWidgets — recent + hot topics loaded on the client. */
import { useEffect, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Sparkles, Clock } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import { queryApi, type QueryHistoryItem, ApiError } from "@/lib/api-client";

interface Props {
  userId: string;
  displayName: string;
}

export function DashboardWidgets({ displayName }: Props) {
  const t = useTranslations("dashboard");
  const tCommon = useTranslations("common");
  const [recent, setRecent] = useState<QueryHistoryItem[] | null>(null);
  const [hot, setHot] = useState<Array<{ text: string; count: number }> | null>(null);

  useEffect(() => {
    let cancelled = false;
    queryApi
      .history(20, 0)
      .then((items) => {
        if (cancelled) return;
        setRecent(items);
        // Derive "hot topics" by counting lowercased query prefixes.
        const counts = new Map<string, number>();
        for (const it of items) {
          const key = it.query_text.trim().toLowerCase().slice(0, 40);
          if (!key) continue;
          counts.set(key, (counts.get(key) ?? 0) + 1);
        }
        const ranked = [...counts.entries()]
          .sort((a, b) => b[1] - a[1])
          .slice(0, 5)
          .map(([text, count]) => ({ text, count }));
        setHot(ranked);
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof ApiError) {
          // eslint-disable-next-line no-console
          console.error("Dashboard load failed:", e.code, e.message);
        }
        setRecent([]);
        setHot([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          {recent === null
            ? `${t("welcome", { name: displayName })}`
            : recent.length === 0
              ? `${t("welcomeEmpty", { name: displayName })}`
              : `${t("welcome", { name: displayName })}`}
        </h1>
        {recent !== null && recent.length === 0 && (
          <div className="mt-3">
            <Button asChild>
              <Link href="/query">{t("askFirstQuestion")}</Link>
            </Button>
          </div>
        )}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Sparkles className="h-4 w-4" /> {t("hotTopics")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {hot === null ? (
              <div className="space-y-2">
                <Skeleton className="h-6 w-full" />
                <Skeleton className="h-6 w-3/4" />
                <Skeleton className="h-6 w-2/3" />
              </div>
            ) : hot.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("hotTopicsEmpty")}</p>
            ) : (
              <ul className="space-y-1 text-sm">
                {hot.map((h) => (
                  <li key={h.text} className="flex items-center justify-between">
                    <span className="truncate">{h.text}</span>
                    <span className="text-xs text-muted-foreground">
                      {t("hotTopicQueries", { count: h.count })}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Clock className="h-4 w-4" /> {t("recentQueries")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {recent === null ? (
              <div className="space-y-2">
                <Skeleton className="h-6 w-full" />
                <Skeleton className="h-6 w-5/6" />
                <Skeleton className="h-6 w-2/3" />
              </div>
            ) : recent.length === 0 ? (
              <EmptyState title={t("recentQueriesEmpty")} />
            ) : (
              <ul className="space-y-1 text-sm">
                {recent.slice(0, 5).map((q) => (
                  <li key={q.id} className="truncate">
                    <Link
                      href={`/query/history?id=${encodeURIComponent(q.id)}`}
                      className="hover:underline"
                    >
                      {q.query_text}
                    </Link>
                  </li>
                ))}
                <li className="pt-2">
                  <Button asChild variant="link" size="sm" className="h-auto p-0">
                    <Link href="/query/history">{tCommon("next")} →</Link>
                  </Button>
                </li>
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
