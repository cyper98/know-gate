"use client";

/** RoleGate — render children only if the current user has one of `allowed` roles. */
import { useUser } from "@/components/user-provider";
import type { User } from "@/lib/api-types";

interface Props {
  allowed: string[];
  fallback?: React.ReactNode;
  children: React.ReactNode;
}

export function RoleGate({ allowed, fallback = null, children }: Props) {
  const { user } = useUser();
  if (!user) return <>{fallback}</>;
  const ok = user.roles.some((r: string) => allowed.includes(r));
  if (!ok) return <>{fallback}</>;
  return <>{children}</>;
}

/** Hook variant for inline checks. */
export function useHasRole(user: User | null, allowed: string[]): boolean {
  if (!user) return false;
  return user.roles.some((r) => allowed.includes(r));
}
