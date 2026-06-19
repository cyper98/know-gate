"use client";

/** AdminGroupsTable — list + create + delete + add member. */
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Plus, Trash2, FolderTree, UserPlus } from "lucide-react";

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
  groupsApi,
  usersApi,
  type Group,
  type User,
  ApiError,
} from "@/lib/api-client";

export function AdminGroupsTable() {
  const t = useTranslations("admin.groups");
  const tCommon = useTranslations("common");
  const [items, setItems] = useState<Group[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const reload = () => {
    groupsApi
      .list()
      .then((p) => setItems(p.data))
      .catch((e) => {
        if (e instanceof ApiError) setError(e.message);
        setItems([]);
      });
  };
  useEffect(reload, []);

  const remove = async (g: Group) => {
    if (!window.confirm(t("deleteConfirm", { name: g.name }))) return;
    setBusy(g.id);
    try {
      await groupsApi.delete(g.id);
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
        <CreateGroupDialog onCreated={reload} />
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
          <Skeleton className="h-24 w-full" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">{t("name")}</th>
                  <th className="py-2 pr-3 font-medium">{t("description")}</th>
                  <th className="py-2 pr-3 font-medium">{t("members")}</th>
                  <th className="py-2 pr-3 font-medium">{t("documents")}</th>
                  <th className="py-2 pr-3 font-medium">
                    {tCommon("actions")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((g) => (
                  <tr key={g.id} className="border-b last:border-0">
                    <td className="py-2 pr-3">
                      <div className="flex items-center gap-2">
                        <FolderTree className="h-4 w-4 text-muted-foreground" />
                        {g.name}
                      </div>
                    </td>
                    <td className="py-2 pr-3 text-muted-foreground">
                      {g.description ?? "\u2014"}
                    </td>
                    <td className="py-2 pr-3">
                      <Badge variant="outline">{g.user_count ?? 0}</Badge>
                    </td>
                    <td className="py-2 pr-3">
                      <Badge variant="outline">{g.document_count ?? 0}</Badge>
                    </td>
                    <td className="py-2 pr-3">
                      <div className="flex items-center gap-1">
                        <AddMemberPopover
                          group={g}
                          onAdded={() => {
                            reload();
                            setInfo(t("memberAdded"));
                          }}
                          onError={setError}
                        />
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => remove(g)}
                          disabled={busy === g.id}
                          aria-label={tCommon("delete")}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
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

function CreateGroupDialog({ onCreated }: { onCreated: () => void }) {
  const t = useTranslations("admin.groups");
  const tCommon = useTranslations("common");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await groupsApi.create({ name, description: description || undefined });
      setOpen(false);
      setName("");
      setDescription("");
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
          {t("newGroup")}
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
            <Label htmlFor="group-name">{t("name")}</Label>
            <Input
              id="group-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              pattern="[a-z0-9_-]+"
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="group-desc">{t("description")}</Label>
            <Input
              id="group-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
            >
              {tCommon("cancel")}
            </Button>
            <Button type="submit" disabled={busy || !name.trim()}>
              {busy ? "..." : tCommon("create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function AddMemberPopover({
  group,
  onAdded,
  onError,
}: {
  group: Group;
  onAdded: () => void;
  onError: (msg: string) => void;
}) {
  const t = useTranslations("admin.groups");
  const [open, setOpen] = useState(false);
  const [users, setUsers] = useState<User[] | null>(null);
  const [selectedUserId, setSelectedUserId] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open && !users) {
      usersApi
        .list({ limit: 100 })
        .then((p) => setUsers(p.data))
        .catch(() => setUsers([]));
    }
  }, [open, users]);

  const handleAdd = async () => {
    if (!selectedUserId) return;
    setBusy(true);
    try {
      await groupsApi.addMember(group.id, selectedUserId);
      setOpen(false);
      setSelectedUserId("");
      onAdded();
    } catch (e) {
      if (e instanceof ApiError) onError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          size="icon"
          variant="ghost"
          aria-label={t("addMember")}
          title={t("addMember")}
        >
          <UserPlus className="h-4 w-4" />
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("addMemberTitle", { name: group.name })}</DialogTitle>
          <DialogDescription>{t("addMember")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          {users === null ? (
            <Skeleton className="h-9 w-full" />
          ) : (
            <select
              value={selectedUserId}
              onChange={(e) => setSelectedUserId(e.target.value)}
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <option value="">{t("selectUser")}</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.display_name} ({u.email})
                </option>
              ))}
            </select>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleAdd} disabled={busy || !selectedUserId}>
              {busy ? "..." : t("addMember")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
