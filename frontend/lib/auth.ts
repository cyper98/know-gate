/**
 * Server-side auth helpers (Next.js App Router).
 *
 * This file is SERVER-ONLY (uses `next/headers` via `auth-cookies`).
 * For server actions callable from client components, import from
 * `@/lib/auth-actions` instead.
 *
 * Exports:
 * - `getCurrentUser()` — reads the user cookie, returns `User` or `null`.
 * - `requireAuth()` — server-component guard; redirects to /login if no user.
 * - `requireRole(roles)` — server-component guard; redirects on missing role.
 * - `hasPermission(user, permission)` — client-side permission check.
 */

import { redirect } from "next/navigation";

import type { Permission, User } from "./api-types";
import { readUserJson } from "./auth-cookies";

const UserSchema = z.object({
  id: z.string(),
  email: z.string().email(),
  display_name: z.string(),
  language_pref: z.string().optional(),
  status: z.enum(["active", "inactive", "pending"]),
  roles: z.array(z.string()).default([]),
  last_login_at: z.string().optional(),
  created_at: z.string().optional(),
  updated_at: z.string().optional(),
});

import { z } from "zod";

export function getCurrentUser(): User | null {
  const raw = readUserJson();
  if (!raw) return null;
  try {
    const parsed = UserSchema.parse(JSON.parse(raw));
    return parsed as User;
  } catch {
    return null;
  }
}

export async function requireAuth(): Promise<User> {
  const user = getCurrentUser();
  if (!user) {
    redirect("/login");
  }
  return user;
}

export async function requireRole(allowed: string[]): Promise<User> {
  const user = await requireAuth();
  const ok = user.roles.some((r) => allowed.includes(r));
  if (!ok) {
    // Silent bounce — the dashboard is the closest landing page a regular
    // user can see. Surfacing the reason would require either a banner
    // state plumbing or a query param the dashboard reads; deferred to a
    redirect("/dashboard");
  }
  return user;
}

export function hasPermission(user: User, required: Permission): boolean {
  // Mirror the backend's flat role → permission map; the source of truth
  // is `backend/app/auth/permissions.py`. We re-derive the same map here
  // so the UI can hide controls without round-tripping the API.
  const map: Record<string, ReadonlySet<Permission>> = {
    admin: new Set<Permission>([
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
    ]),
    editor: new Set<Permission>(["view_doc", "edit_doc_metadata"]),
    member: new Set<Permission>(["view_doc"]),
  };
  for (const role of user.roles) {
    const perms = map[role];
    if (perms && perms.has(required)) return true;
  }
  return false;
}
