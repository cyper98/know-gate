"use client";

/** AdminSettingsView — read-only system settings display. */
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Settings as SettingsIcon } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { settingsApi, type SystemSettings, ApiError } from "@/lib/api-client";

export function AdminSettingsView() {
  const t = useTranslations("admin.settings");
  const [data, setData] = useState<SystemSettings | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    settingsApi
      .get()
      .then(setData)
      .catch((e) => {
        if (e instanceof ApiError) setError(e.message);
      });
  }, []);

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }
  if (!data) return <Skeleton className="h-48 w-full" />;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <SettingsIcon className="h-4 w-4" /> {t("title")}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <Row label={t("defaultLanguage")} value={data.default_language} />
        <Row
          label={t("rateLimit")}
          value={`${data.rate_limit_query_per_minute} / min`}
        />
        <Row
          label={t("retentionDays")}
          value={`${data.audit_retention_days} d`}
        />
        <Row
          label={t("feedbackRetention")}
          value={`${data.feedback_retention_days} d`}
        />
        <Row label={t("maxDocSize")} value={`${data.max_doc_size_mb} MB`} />
        <Row
          label={t("allowSignup")}
          value={data.allow_signup ? t("yes") : t("no")}
        />
        <p className="text-xs text-muted-foreground">{t("readOnly")}</p>
      </CardContent>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between border-b pb-2 last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}
