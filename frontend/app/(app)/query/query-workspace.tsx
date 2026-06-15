"use client";

/** QueryWorkspace — search bar + filter sidebar + answer/citation pane. */
import { useState } from "react";
import { useTranslations } from "next-intl";
import { Search, Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FilterSidebar, EMPTY_FILTERS, type QueryFilters } from "@/components/filter-sidebar";
import { CitationCard } from "@/components/citation-card";
import { FeedbackButtons } from "@/components/feedback-buttons";
import { EmptyState } from "@/components/empty-state";
import { queryApi, type QueryResponse, ApiError, type Citation } from "@/lib/api-client";

export function QueryWorkspace() {
  const t = useTranslations("query");
  const tErrors = useTranslations("errors");
  const [question, setQuestion] = useState("");
  const [filters, setFilters] = useState<QueryFilters>(EMPTY_FILTERS);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    const q = question.trim();
    if (!q || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const r = await queryApi.ask({
        question: q,
        language: filters.language || undefined,
      });
      setResult(r);
    } catch (e) {
      if (e instanceof ApiError) {
        setError(tErrors(e.code as Parameters<typeof tErrors>[0]));
      } else {
        setError(tErrors("network"));
      }
      setResult(null);
    } finally {
      setSubmitting(false);
    }
  };

  const reset = () => {
    setResult(null);
    setError(null);
    setQuestion("");
  };

  return (
    <div className="grid gap-4 md:grid-cols-[260px_1fr]">
      <aside>
        <FilterSidebar value={filters} onChange={setFilters} />
      </aside>
      <div className="space-y-4">
        <Card>
          <CardContent className="p-3">
            <div className="flex gap-2">
              <Input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder={t("placeholder")}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void submit();
                  }
                }}
                disabled={submitting}
                className="flex-1"
              />
              <Button onClick={submit} disabled={!question.trim() || submitting}>
                <Search className="h-4 w-4" />
                {t("submit")}
              </Button>
              {result && (
                <Button variant="ghost" onClick={reset}>
                  <X className="h-4 w-4" />
                  {t("askNew")}
                </Button>
              )}
            </div>
          </CardContent>
        </Card>

        {submitting && (
          <Card>
            <CardContent className="space-y-3 p-6">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Sparkles className="h-4 w-4 animate-pulse" />
                {t("searching", { count: 0 })}
              </div>
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-5/6" />
              <Skeleton className="h-4 w-2/3" />
            </CardContent>
          </Card>
        )}

        {error && !submitting && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {result && !submitting && (
          <div className="space-y-4">
            <Card>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between gap-2">
                  <CardTitle className="text-base">{t("answer")}</CardTitle>
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    {result.cache_hit && <Badge variant="success">{t("cacheHit")}</Badge>}
                    <span>{t("latencyMs", { ms: result.latency_ms })}</span>
                    {result.llm_model && <Badge variant="outline">{result.llm_model}</Badge>}
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {result.no_answer || !result.answer ? (
                  <EmptyState
                    title={t("noResult")}
                    description={result.no_result?.message ?? t("noResultHint")}
                  />
                ) : (
                  <p className="whitespace-pre-wrap text-sm leading-relaxed">
                    {result.answer}
                  </p>
                )}
                {result.citations.length > 0 && (
                  <p className="text-xs text-muted-foreground">
                    {t("basedOnN", { count: result.citations.length })}
                  </p>
                )}
                <div className="border-t pt-3">
                  <FeedbackButtons queryId={result.query_id} />
                </div>
              </CardContent>
            </Card>

            {result.citations.length > 0 && (
              <div className="space-y-2">
                <h3 className="text-sm font-semibold">{t("sources")}</h3>
                <div className="space-y-2">
                  {result.citations.map((c: Citation) => (
                    <CitationCard key={c.chunk_id} citation={c} />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
