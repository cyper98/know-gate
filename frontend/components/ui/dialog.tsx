/** Dialog — modal overlay with backdrop + content. shadcn-style. */
"use client";

import * as React from "react";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
}

export function Dialog({ open, onOpenChange, children }: DialogProps) {
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onOpenChange(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={() => onOpenChange(false)}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="relative z-10 w-full max-w-md rounded-lg border bg-background p-6 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          aria-label="Close"
          onClick={() => onOpenChange(false)}
          className="absolute right-3 top-3 rounded-md p-1 text-muted-foreground hover:bg-accent"
        >
          <X className="h-4 w-4" />
        </button>
        {children}
      </div>
    </div>
  );
}

export function DialogHeader({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("mb-4 space-y-1", className)}>{children}</div>;
}

export function DialogTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="text-lg font-semibold">{children}</h2>;
}

export function DialogDescription({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

export function DialogFooter({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("mt-4 flex justify-end gap-2", className)}>{children}</div>;
}

export function DialogContent({ children }: { children: React.ReactNode }) {
  return <div className="space-y-3">{children}</div>;
}

export const DialogTrigger = ({ children, asChild: _asChild, ...props }: { children: React.ReactNode; asChild?: boolean } & React.ButtonHTMLAttributes<HTMLButtonElement>) => (
  <button type="button" {...props}>
    {children}
  </button>
);
