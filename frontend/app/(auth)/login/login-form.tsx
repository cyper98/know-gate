"use client";

/** LoginForm — client component for the email+password + magic-link UI. */
import { useState, useTransition } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import { loginAction, requestMagicLinkAction } from "@/lib/auth-actions";
import { authApi } from "@/lib/api-client";

export function LoginForm() {
  const t = useTranslations("auth");
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") ?? "/dashboard";

  const [error, setError] = useState<string | null>(null);
  const [magicSent, setMagicSent] = useState(false);
  const [pending, start] = useTransition();
  const [oauthPending, setOauthPending] = useState<"google" | "github" | null>(null);

  const onSubmit = (form: FormData) => {
    setError(null);
    start(async () => {
      const r = await loginAction(form);
      if (r.ok) {
        router.push(next);
        router.refresh();
      } else {
        setError(r.error ?? "Login failed");
      }
    });
  };

  const onMagic = (form: FormData) => {
    setError(null);
    start(async () => {
      const r = await requestMagicLinkAction(form);
      if (r.ok) {
        setMagicSent(true);
      } else {
        setError(r.error ?? "Failed");
      }
    });
  };

  const onOAuth = async (provider: "google" | "github") => {
    setError(null);
    setOauthPending(provider);
    try {
      const url = await authApi.startOAuth(provider);
      window.location.href = url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "OAuth failed");
      setOauthPending(null);
    }
  };

  return (
    <div className="w-full max-w-sm space-y-6">
      <div className="space-y-2 text-center">
        <h1 className="text-2xl font-bold tracking-tight">{t("loginTitle")}</h1>
        <p className="text-sm text-muted-foreground">{t("loginSubtitle")}</p>
      </div>
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {magicSent && (
        <Alert variant="success">
          <AlertDescription>{t("magicLinkSent")}</AlertDescription>
        </Alert>
      )}
      <form action={onSubmit} className="space-y-3">
        <div className="space-y-1.5">
          <Label htmlFor="email">{t("emailPlaceholder")}</Label>
          <Input
            id="email"
            name="email"
            type="email"
            placeholder={t("emailPlaceholder")}
            required
            autoComplete="email"
            autoFocus
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="password">{t("passwordPlaceholder")}</Label>
          <Input
            id="password"
            name="password"
            type="password"
            placeholder={t("passwordPlaceholder")}
            required
            minLength={8}
            autoComplete="current-password"
          />
        </div>
        <Button type="submit" className="w-full" disabled={pending}>
          {pending ? t("signingIn") : t("signInWithEmail")}
        </Button>
      </form>
      <div className="flex items-center gap-3">
        <Separator className="flex-1" />
        <span className="text-xs text-muted-foreground">{t("or")}</span>
        <Separator className="flex-1" />
      </div>
      <div className="space-y-2">
        <Button
          type="button"
          variant="outline"
          className="w-full"
          onClick={() => onOAuth("google")}
          disabled={oauthPending !== null}
        >
          {t("signInWithGoogle")}
        </Button>
        <Button
          type="button"
          variant="outline"
          className="w-full"
          onClick={() => onOAuth("github")}
          disabled={oauthPending !== null}
        >
          {t("signInWithGithub")}
        </Button>
      </div>
      <form action={onMagic} className="space-y-2">
        <div className="space-y-1.5">
          <Label htmlFor="magic-email">{t("requestMagicLink")}</Label>
          <Input
            id="magic-email"
            name="email"
            type="email"
            placeholder={t("emailPlaceholder")}
            required
            autoComplete="email"
          />
        </div>
        <Button type="submit" variant="ghost" className="w-full" disabled={pending}>
          {t("requestMagicLink")}
        </Button>
      </form>
      <p className="text-center text-xs text-muted-foreground">{t("noAccount")}</p>
    </div>
  );
}
