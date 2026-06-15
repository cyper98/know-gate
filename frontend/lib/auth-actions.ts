"use server";

/**
 * Server actions — auth flow entry points that can be called directly from
 * client components. The `"use server"` directive tells Next.js to keep
 * this file on the server side of the bundle, so the client can import
 * the exported functions as opaque references.
 *
 * The actual API call + cookie I/O lives here so we can use the
 * backend's `/api/v1/auth/*` endpoints server-side without exposing
 * them to the browser.
 */

import { redirect } from "next/navigation";
import { z } from "zod";

import {
  clearAuthCookies,
  readRefreshToken,
  setAuthCookies,
} from "./auth-cookies";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? process.env.KG_API_URL ?? "";
const INTERNAL_API_URL = process.env.KG_INTERNAL_API_URL ?? API_URL;

const LoginSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8).max(128),
});

const MagicLinkSchema = z.object({ email: z.string().email() });

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

const TokenPairSchema = z.object({
  access_token: z.string(),
  refresh_token: z.string(),
  token_type: z.literal("bearer"),
  expires_in: z.number().int().positive(),
  user: UserSchema,
});

interface ServerActionResult {
  ok: boolean;
  error?: string;
}

async function callApi<T>(path: string, init: RequestInit): Promise<T> {
  const url = `${INTERNAL_API_URL}${path}`;
  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(init.headers ?? {}),
      },
      cache: "no-store",
    });
  } catch (e) {
    throw new Error(
      `Cannot reach the API server at ${url}: ${e instanceof Error ? e.message : String(e)}`,
    );
  }
  const text = await res.text();
  const parsed: unknown = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const body = (parsed ?? {}) as { error?: { code?: string; message?: string } };
    const msg = body.error?.message ?? `Request failed (${res.status})`;
    throw new Error(msg);
  }
  return parsed as T;
}

export async function loginAction(formData: FormData): Promise<ServerActionResult> {
  const parsed = LoginSchema.safeParse({
    email: formData.get("email"),
    password: formData.get("password"),
  });
  if (!parsed.success) {
    return { ok: false, error: "Please enter a valid email and password." };
  }
  try {
    const pair = await callApi<unknown>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(parsed.data),
    });
    const tokens = TokenPairSchema.parse(pair);
    setAuthCookies({
      accessToken: tokens.access_token,
      accessExpiresInSec: tokens.expires_in,
      refreshToken: tokens.refresh_token,
      userJson: JSON.stringify(tokens.user),
    });
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "Login failed" };
  }
}

export async function requestMagicLinkAction(
  formData: FormData,
): Promise<ServerActionResult> {
  const parsed = MagicLinkSchema.safeParse({ email: formData.get("email") });
  if (!parsed.success) {
    return { ok: false, error: "Please enter a valid email." };
  }
  try {
    await callApi<unknown>("/api/v1/auth/magic-link", {
      method: "POST",
      body: JSON.stringify(parsed.data),
    });
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "Failed" };
  }
}

export async function verifyMagicLinkAction(
  token: string,
): Promise<ServerActionResult> {
  try {
    const pair = await callApi<unknown>(
      `/api/v1/auth/magic-link/verify?token=${encodeURIComponent(token)}`,
      { method: "GET" },
    );
    const tokens = TokenPairSchema.parse(pair);
    setAuthCookies({
      accessToken: tokens.access_token,
      accessExpiresInSec: tokens.expires_in,
      refreshToken: tokens.refresh_token,
      userJson: JSON.stringify(tokens.user),
    });
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "Failed" };
  }
}

export async function logoutAction(): Promise<void> {
  const refresh = readRefreshToken();
  try {
    if (refresh) {
      await callApi<unknown>("/api/v1/auth/logout", {
        method: "POST",
        headers: { Authorization: `Bearer ${refresh}` },
      });
    }
  } catch {
    // best-effort; clear local state regardless
  }
  clearAuthCookies();
  redirect("/login");
}
