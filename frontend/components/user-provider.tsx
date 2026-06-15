"use client";

/** UserProvider — exposes the current user from the server-injected cookie
 *  to client components via React context. Hydration-safe: the server layout
 *  sets the same data on `<UserProvider initialUser={...}>` so the first
 *  client render matches. */
import { createContext, useContext } from "react";

import type { User } from "@/lib/api-types";

const UserContext = createContext<{ user: User | null }>({ user: null });

interface Props {
  user: User | null;
  children: React.ReactNode;
}

export function UserProvider({ user, children }: Props) {
  return <UserContext.Provider value={{ user }}>{children}</UserContext.Provider>;
}

export function useUser(): { user: User | null } {
  return useContext(UserContext);
}
