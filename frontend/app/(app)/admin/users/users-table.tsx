"use client";

/** AdminUsersTable — invite + list + soft-delete + role management. */
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { UserPlus, Trash2, ShieldPlus, X } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
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
  usersApi,
  rolesApi,
  type User,
  type Role,
  ApiError,
} from "@/lib/api-client";

export function AdminUsersTable() {
  const t = useTranslations("admin.users");
  const tCommon = useTranslations("common");
  const [items, setItems] = useState<User[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [allRoles, setAllRoles] = useState<Role[]>([]);

  const reload = () => {
    usersApi
      .list()
      .then((page) => setItems(page.data))
      .catch((e) => {
        if (e instanceof ApiError) setError(e.message);
        setItems([]);
      });
  };

  useEffect(() => {
    reload();
    rolesApi
      .list({ limit: 100 })
      .then((p) => setAllRoles(p.data))
      .catch(() => {});
  }, []);

  const remove = async (u: User) => {
    if (!window.confirm(t("deleteConfirm", { name: u.display_name }))) return;
    setBusy(u.id);
    try {
      await usersApi.delete(u.id);
      reload();
    } catch (e) {
      if (e instanceof ApiError) setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const handleAssignRole = async (userId: string, roleId: string) => {
    setBusy(userId);
    try {
      await usersApi.assignRole(userId, roleId);
      setInfo(t("roleAssigned"));
      reload();
    } catch (e) {
      if (e instanceof ApiError) setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const handleRevokeRole = async (userId: string, roleId: string) => {
    setBusy(userId);
    try {
      await usersApi.revokeRole(userId, roleId);
      setInfo(t("roleRevoked"));
      reload();
    } catch (e) {
      if (e instanceof ApiError) setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  // Build role name -> id map for revoking
  const roleMap = new Map(allRoles.map((r) => [r.name, r.id]));

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base">{t("title")}</CardTitle>
        <InviteDialog
          onCreated={() => {
            reload();
            setInfo(t("inviteSent", { email: "user" }));
          }}
        />
      </CardHeader>
      <CardContent className="space-y-3">
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {info && (
          <Alert variant="success">
            <AlertDescription>{info}</AlertDescription>
          </Alert>
        )}
        {items === null ? (
          <Skeleton className="h-32 w-full" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">{t("displayName")}</th>
                  <th className="py-2 pr-3 font-medium">{t("email")}</th>
                  <th className="py-2 pr-3 font-medium">{t("roles")}</th>
                  <th className="py-2 pr-3 font-medium">{t("status")}</th>
                  <th className="py-2 pr-3 font-medium">
                    {tCommon("actions")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((u) => (
                  <tr key={u.id} className="border-b last:border-0">
                    <td className="py-2 pr-3">{u.display_name}</td>
                    <td className="py-2 pr-3 text-muted-foreground">
                      {u.email}
                    </td>
                    <td className="py-2 pr-3">
                      <div className="flex flex-wrap items-center gap-1">
                        {u.roles.map((r) => {
                          const roleId = roleMap.get(r);
                          return (
                            <Badge
                              key={r}
                              variant="outline"
                              className="gap-1 pr-1"
                            >
                              {r}
                              {roleId && (
                                <button
                                  onClick={() => handleRevokeRole(u.id, roleId)}
                                  disabled={busy === u.id}
                                  className="ml-0.5 rounded-full hover:bg-destructive/20"
                                  aria-label={t("removeRole")}
                                >
                                  <X className="h-3 w-3" />
                                </button>
                              )}
                            </Badge>
                          );
                        })}
                        <AddRoleDialog
                          user={u}
                          allRoles={allRoles}
                          onAssign={(roleId) => handleAssignRole(u.id, roleId)}
                          busy={busy === u.id}
                        />
                      </div>
                    </td>
                    <td className="py-2 pr-3">
                      <Badge
                        variant={
                          u.status === "active" ? "success" : "secondary"
                        }
                      >
                        {u.status}
                      </Badge>
                    </td>
                    <td className="py-2 pr-3">
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => remove(u)}
                        disabled={busy === u.id}
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

function InviteDialog({ onCreated }: { onCreated: () => void }) {
  const t = useTranslations("admin.users");
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await usersApi.invite({ email, display_name: name, role_ids: [] });
      setOpen(false);
      setEmail("");
      setName("");
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
          <UserPlus className="h-4 w-4" />
          {t("invite")}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("inviteTitle")}</DialogTitle>
          <DialogDescription>
            The new user will receive an email.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-3">
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="invite-name">{t("displayName")}</Label>
            <Input
              id="invite-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="invite-email">{t("email")}</Label>
            <Input
              id="invite-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <DialogFooter>
            <Button type="submit" disabled={busy}>
              {busy ? "..." : t("invite")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function AddRoleDialog({
  user,
  allRoles,
  onAssign,
  busy,
}: {
  user: User;
  allRoles: Role[];
  onAssign: (roleId: string) => void;
  busy: boolean;
}) {
  const t = useTranslations("admin.users");
  const [open, setOpen] = useState(false);
  const [selectedRoleId, setSelectedRoleId] = useState("");

  // Filter out roles the user already has
  const availableRoles = allRoles.filter((r) => !user.roles.includes(r.name));

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button
          className="inline-flex items-center rounded-full border border-dashed px-1.5 py-0.5 text-xs text-muted-foreground hover:border-primary hover:text-primary"
          aria-label={t("addRole")}
          title={t("addRole")}
        >
          <ShieldPlus className="h-3 w-3" />
        </button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {t("addRoleTitle", { name: user.display_name })}
          </DialogTitle>
          <DialogDescription>{t("addRole")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <select
            value={selectedRoleId}
            onChange={(e) => setSelectedRoleId(e.target.value)}
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <option value="">{t("selectRole")}</option>
            {availableRoles.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                onAssign(selectedRoleId);
                setOpen(false);
              }}
              disabled={busy || !selectedRoleId}
            >
              {t("addRole")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
