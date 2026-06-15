"use client";

/** LangSwitcher — VI / EN dropdown, writes preference to the next-intl cookie. */
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { localeLabels, locales, type Locale } from "@/i18n/config";

const LOCALE_COOKIE = "NEXT_LOCALE";

export function LangSwitcher() {
  const t = useTranslations("nav");
  const router = useRouter();
  const current = useLocale();
  const [pending, start] = useTransition();

  const onChange = (next: string) => {
    if (next === current) return;
    document.cookie = `${LOCALE_COOKIE}=${next}; path=/; max-age=${60 * 60 * 24 * 365}; SameSite=Lax`;
    start(() => {
      router.refresh();
    });
  };

  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="sr-only">{t("switchLanguage")}</span>
      <select
        aria-label={t("switchLanguage")}
        value={current}
        onChange={(e) => onChange(e.target.value)}
        disabled={pending}
        className="h-8 rounded-md border border-input bg-background px-2 text-sm"
      >
        {locales.map((l: Locale) => (
          <option key={l} value={l}>
            {localeLabels[l]}
          </option>
        ))}
      </select>
    </label>
  );
}
