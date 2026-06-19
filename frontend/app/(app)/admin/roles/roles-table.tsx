"use client";

/** AdminRolesTable — list + create + delete. */
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Plus, Trash2, Shield } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  rolesApi,
  type Role,
  type Permission,
  ApiError,
} from "@/lib/api-client";

const ALL_PERMISSIONS: Permission[] = [
  "view_doc",
  "edit_doc_metadata",
  "delete_doc",
  "manage_users",
  "manage_roles",
  "manage_groups",
  "manage_sources",
  "manage_settings",
  "invite_user",
  "view_audit_log",
];

export function AdminRolesTable() {
  const t = useTranslations("admin.roles");
  const tCommon = useTranslations("common");
  const [items, setItems] = useState<Role[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = () => {
    rolesApi
      .list()
      .then((p) => setItems(p.data))
      .catch((e) => {
        if (e instanceof ApiError) setError(e.message);
        setItems([]);
      });
  };
  useEffect(reload, []);

  const remove = async (r: Role) => {
    if (!window.confirm(t("deleteConfirm", { name: r.name }))) return;
    setBusy(r.id);
    try {
      await rolesApi.delete(r.id);
      reload();
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.code === "E6" || e.code === "E12") setError(t("inUseBlock"));
        else setError(e.message);
      }
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base">{t("title")}</CardTitle>
        <CreateRoleDialog onCreated={reload} />
      </CardHeader>
      <CardContent className="space-y-3">
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {items === null ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">{t("name")}</th>
                  <th className="py-2 pr-3 font-medium">{t("permissions")}</th>
                  <th className="py-2 pr-3 font-medium">
                    {tCommon("actions")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((r) => (
                  <tr key={r.id} className="border-b last:border-0">
                    <td className="py-2 pr-3">
                      <div className="flex items-center gap-2">
                        <Shield className="h-4 w-4 text-muted-foreground" />
                        {r.name}
                        {r.is_static && (
                          <Badge variant="secondary" className="text-[10px]">
                            built-in
                          </Badge>
                        )}
                      </div>
                    </td>
                    <td className="py-2 pr-3">
                      <div className="flex flex-wrap gap-1">
                        {r.permissions.slice(0, 4).map((p) => (
                          <Badge
                            key={p}
                            variant="outline"
                            className="text-[10px]"
                          >
                            {p}
                          </Badge>
                        ))}
                        {r.permissions.length > 4 && (
                          <span className="text-xs text-muted-foreground">
                            +{r.permissions.length - 4}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="py-2 pr-3">
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => remove(r)}
                        disabled={busy === r.id || r.is_static}
                        aria-label={tCommon("delete")}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function CreateRoleDialog({ onCreated }: { onCreated: () => void }) {
  const t = useTranslations("admin.roles");
  const tCommon = useTranslations("common");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selected, setSelected] = useState<Set<Permission>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggle = (p: Permission) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(p)) next.delete(p);
      else next.add(p);
      return next;
    });
  };

  const toggleAll = () => {
    if (selected.size === ALL_PERMISSIONS.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(ALL_PERMISSIONS));
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await rolesApi.create({
        name,
        description: description || undefined,
        permissions: [...selected],
      });
      setOpen(false);
      setName("");
      setDescription("");
      setSelected(new Set());
      onCreated();
    } catch (err) {
      if (err instanceof ApiError) setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm">
          <Plus className="h-4 w-4" />
          {t("newRole")}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("createTitle")}</DialogTitle>
          <DialogDescription>{t("subtitle")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-3">
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="role-name">{t("name")}</Label>
            <Input
              id="role-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="role-desc">{t("description")}</Label>
            <Input
              id="role-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label>{t("permissions")}</Label>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={toggleAll}
                className="h-auto px-2 py-0.5 text-xs"
              >
                {selected.size === ALL_PERMISSIONS.length
                  ? t("deselectAll")
                  : t("selectAll")}
              </Button>
            </div>
            <div className="grid grid-cols-2 gap-1.5">
              {ALL_PERMISSIONS.map((p) => (
                <label
                  key={p}
                  className="flex items-center gap-2 text-sm cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={selected.has(p)}
                    onChange={() => toggle(p)}
                    className="h-4 w-4 rounded border-input"
                  />
                  <span className="text-xs">{p}</span>
                </label>
              ))}
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
            >
              {tCommon("cancel")}
            </Button>
            <Button
              type="submit"
              disabled={busy || !name.trim() || selected.size === 0}
            >
              {busy ? "..." : tCommon("create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
