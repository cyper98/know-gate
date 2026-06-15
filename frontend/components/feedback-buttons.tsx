"use client";

/** FeedbackButtons — good / bad / missing-source trio, posts to /api/v1/feedback. */
import { useState } from "react";
import { ThumbsUp, ThumbsDown, FileQuestion } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useTranslations } from "next-intl";
import { feedbackApi, ApiError, type FeedbackType } from "@/lib/api-client";

interface Props {
  queryId: string;
}

export function FeedbackButtons({ queryId }: Props) {
  const t = useTranslations("query");
  const [busy, setBusy] = useState<FeedbackType | null>(null);
  const [done, setDone] = useState<FeedbackType | null>(null);

  const submit = async (kind: FeedbackType) => {
    if (done) return;
    setBusy(kind);
    try {
      await feedbackApi.submit({ query_id: queryId, feedback_type: kind });
      setDone(kind);
    } catch (e) {
      // Surface as a non-blocking error — keep the buttons usable.
      if (e instanceof ApiError) {
        // eslint-disable-next-line no-console
        console.error("Feedback submit failed:", e.code, e.message);
      }
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex items-center gap-1">
      <Button
        variant={done === "good" ? "default" : "ghost"}
        size="sm"
        disabled={busy !== null}
        onClick={() => submit("good")}
        aria-label={t("feedbackGood")}
      >
        <ThumbsUp className="h-4 w-4" />
        {t("feedbackGood")}
      </Button>
      <Button
        variant={done === "bad" ? "default" : "ghost"}
        size="sm"
        disabled={busy !== null}
        onClick={() => submit("bad")}
        aria-label={t("feedbackBad")}
      >
        <ThumbsDown className="h-4 w-4" />
        {t("feedbackBad")}
      </Button>
      <Button
        variant={done === "source_missing" ? "default" : "ghost"}
        size="sm"
        disabled={busy !== null}
        onClick={() => submit("source_missing")}
        aria-label={t("feedbackMissing")}
      >
        <FileQuestion className="h-4 w-4" />
        {t("feedbackMissing")}
      </Button>
    </div>
  );
}
