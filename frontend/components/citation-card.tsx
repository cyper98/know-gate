"use client";

/** CitationCard — expandable card showing one cited source. */
import { useState } from "react";
import { ExternalLink, ChevronDown, ChevronUp } from "lucide-react";

import type { Citation } from "@/lib/api-types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface Props {
  citation: Citation;
  defaultOpen?: boolean;
}

export function CitationCard({ citation, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <Card className="overflow-hidden">
      <CardContent className="space-y-2 p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono text-muted-foreground">
                [{citation.index}]
              </span>
              <span className="truncate text-sm font-medium">
                {citation.title}
              </span>
              {citation.source && (
                <Badge variant="outline" className="shrink-0">
                  {citation.source}
                </Badge>
              )}
            </div>
            {citation.section_title && (
              <p className="text-xs text-muted-foreground">
                {citation.section_title}
                {citation.page_number ? ` · p. ${citation.page_number}` : ""}
              </p>
            )}
          </div>
          {citation.url && (
            <Button asChild variant="ghost" size="icon" className="shrink-0">
              <a href={citation.url} target="_blank" rel="noreferrer">
                <ExternalLink className="h-4 w-4" />
                <span className="sr-only">Open source</span>
              </a>
            </Button>
          )}
        </div>
        {citation.snippet && (
          <>
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              className="flex w-full items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
              {open ? "Hide preview" : "Show preview"}
            </button>
            <p
              className={cn(
                "rounded-md bg-muted/50 p-2 text-xs leading-relaxed",
                !open && "line-clamp-2",
              )}
            >
              {citation.snippet}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
