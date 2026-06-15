"use client";

/** MagicLinkVerify — exchanges the ?token= in the URL for a JWT pair, then redirects. */
import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { CheckCircle2, XCircle } from "lucide-react";

import { verifyMagicLinkAction } from "@/lib/auth-actions";
import { Button } from "@/components/ui/button";

export function MagicLinkVerify() {
  const t = useTranslations("auth");
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get("token") ?? "";
  const [state, setState] = useState<"pending" | "ok" | "fail">("pending");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!token) {
      setState("fail");
      setMessage(t("verifyMagicLinkFailed"));
      return;
    }
    (async () => {
      const r = await verifyMagicLinkAction(token);
      if (cancelled) return;
      if (r.ok) {
        setState("ok");
        setTimeout(() => router.push("/dashboard"), 600);
      } else {
        setState("fail");
        setMessage(r.error ?? t("verifyMagicLinkFailed"));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, t, router]);

  return (
    <div className="w-full max-w-sm space-y-4 text-center">
      {state === "pending" && (
        <p className="text-sm text-muted-foreground">{t("verifyMagicLinkTitle")}</p>
      )}
      {state === "ok" && (
        <div className="flex flex-col items-center gap-2 text-emerald-600">
          <CheckCircle2 className="h-8 w-8" />
          <p>{t("signingIn")}</p>
        </div>
      )}
      {state === "fail" && (
        <div className="space-y-3">
          <div className="flex flex-col items-center gap-2 text-destructive">
            <XCircle className="h-8 w-8" />
            <p className="text-sm">{message ?? t("verifyMagicLinkFailed")}</p>
          </div>
          <Button asChild variant="outline" className="w-full">
            <a href="/login">{t("verifyMagicLinkBackToLogin")}</a>
          </Button>
        </div>
      )}
    </div>
  );
}
