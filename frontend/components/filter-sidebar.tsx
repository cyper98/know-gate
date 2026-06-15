"use client";

/** FilterSidebar — query filter UI (team, type, language, time range). */
import { useTranslations } from "next-intl";

import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export interface QueryFilters {
  team: string;
  type: string;
  language: string;
  timeRange: "all" | "7d" | "30d" | "90d";
}

export const EMPTY_FILTERS: QueryFilters = {
  team: "",
  type: "",
  language: "",
  timeRange: "all",
};

interface Props {
  value: QueryFilters;
  onChange: (v: QueryFilters) => void;
}

export function FilterSidebar({ value, onChange }: Props) {
  const t = useTranslations("query");
  const tCommon = useTranslations("common");
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{t("filters")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="f-team">{t("filterTeam")}</Label>
          <input
            id="f-team"
            type="text"
            className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm"
            value={value.team}
            onChange={(e) => onChange({ ...value, team: e.target.value })}
            placeholder={t("filterTeam")}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="f-type">{t("filterType")}</Label>
          <select
            id="f-type"
            className="flex h-9 w-full rounded-md border border-input bg-background px-2 text-sm shadow-sm"
            value={value.type}
            onChange={(e) => onChange({ ...value, type: e.target.value })}
          >
            <option value="">{tCommon("all")}</option>
            <option value="pdf">PDF</option>
            <option value="doc">Document</option>
            <option value="sheet">Sheet</option>
            <option value="slide">Slide</option>
          </select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="f-lang">{t("filterLanguage")}</Label>
          <select
            id="f-lang"
            className="flex h-9 w-full rounded-md border border-input bg-background px-2 text-sm shadow-sm"
            value={value.language}
            onChange={(e) => onChange({ ...value, language: e.target.value })}
          >
            <option value="">{tCommon("all")}</option>
            <option value="en">English</option>
            <option value="vi">Tiếng Việt</option>
          </select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="f-time">{t("filterTimeRange")}</Label>
          <select
            id="f-time"
            className="flex h-9 w-full rounded-md border border-input bg-background px-2 text-sm shadow-sm"
            value={value.timeRange}
            onChange={(e) =>
              onChange({ ...value, timeRange: e.target.value as QueryFilters["timeRange"] })
            }
          >
            <option value="all">{tCommon("all")}</option>
            <option value="7d">{t("filter7Days")}</option>
            <option value="30d">{t("filter30Days")}</option>
            <option value="90d">{t("filter90Days")}</option>
          </select>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="w-full"
          onClick={() => onChange(EMPTY_FILTERS)}
        >
          {tCommon("clear")}
        </Button>
      </CardContent>
    </Card>
  );
}
