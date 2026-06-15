/**
 * Cookie I/O for the JWT pair.
 *
 * Tokens are stored in two non-HttpOnly cookies (`kg_at`, `kg_rt`) so that
 * the browser can include them on cross-origin API calls (the access token
 * is also read on the client by `api-client.ts` to inject the
 * `Authorization: Bearer` header).
 *
 * The cookies are set with `SameSite=Lax` so OAuth callbacks and
 * magic-link verifications work, and `Secure` in production. We do NOT
 * mark them HttpOnly because the client needs to read `kg_at` to attach
 * it to API requests; if XSS becomes a concern we can move to a BFF
 * proxy and switch to HttpOnly without touching the call sites.
 */

import { cookies } from "next/headers";

export const ACCESS_COOKIE = "kg_at";
export const REFRESH_COOKIE = "kg_rt";
export const USER_COOKIE = "kg_user";

const ONE_DAY_SEC = 60 * 60 * 24;
const THIRTY_DAYS_SEC = 30 * ONE_DAY_SEC;

function isProd(): boolean {
  return process.env.NODE_ENV === "production";
}

export function setAuthCookies(args: {
  accessToken: string;
  accessExpiresInSec: number;
  refreshToken: string;
  userJson: string;
}): void {
  const jar = cookies();
  const secure = isProd();
  jar.set(ACCESS_COOKIE, args.accessToken, {
    httpOnly: false,
    sameSite: "lax",
    secure,
    path: "/",
    maxAge: args.accessExpiresInSec,
  });
  jar.set(REFRESH_COOKIE, args.refreshToken, {
    httpOnly: false,
    sameSite: "lax",
    secure,
    path: "/",
    maxAge: THIRTY_DAYS_SEC,
  });
  jar.set(USER_COOKIE, args.userJson, {
    httpOnly: false,
    sameSite: "lax",
    secure,
    path: "/",
    maxAge: THIRTY_DAYS_SEC,
  });
}

export function clearAuthCookies(): void {
  const jar = cookies();
  jar.delete(ACCESS_COOKIE);
  jar.delete(REFRESH_COOKIE);
  jar.delete(USER_COOKIE);
}

export function readAccessToken(): string | null {
  return cookies().get(ACCESS_COOKIE)?.value ?? null;
}

export function readRefreshToken(): string | null {
  return cookies().get(REFRESH_COOKIE)?.value ?? null;
}

export function readUserJson(): string | null {
  return cookies().get(USER_COOKIE)?.value ?? null;
}
