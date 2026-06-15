/**
 * Next.js middleware — auth gate + i18n.
 *
 * Runs on every request before the page renders. Responsibilities:
 *  1. Skip API, static, and Next.js internal paths.
 *  2. If the request is for a protected path and the `kg_at` cookie is
 *     missing, redirect to `/login?next=<original>`.
 *  3. Add a `Vary: Cookie` header so caches don't mix localized responses.
 *
 * The actual `getCurrentUser()` parsing happens in server components via
 * `lib/auth.ts`; the middleware only checks the presence of the cookie as
 * a fast first pass. A real verification (decoding the JWT) lives on the
 * server side because `jsonwebtoken` / `jose` is too heavy for the edge
 * runtime and the API itself is the source of truth.
 */

import { NextResponse, type NextRequest } from "next/server";

import { ACCESS_COOKIE } from "@/lib/auth-cookies";

const PROTECTED_PREFIXES = [
  "/dashboard",
  "/query",
  "/admin",
];

const PUBLIC_PATHS = new Set(["/", "/login", "/magic-link/verify"]);

function isProtected(pathname: string): boolean {
  return PROTECTED_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

function isAlwaysPublic(pathname: string): boolean {
  return (
    PUBLIC_PATHS.has(pathname) ||
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api") ||
    pathname.startsWith("/static") ||
    pathname === "/favicon.ico" ||
    pathname === "/robots.txt" ||
    pathname === "/sitemap.xml" ||
    /\.[a-zA-Z0-9]+$/.test(pathname) // any file with an extension
  );
}

export function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;

  if (isAlwaysPublic(pathname)) {
    return NextResponse.next();
  }

  const hasToken = Boolean(req.cookies.get(ACCESS_COOKIE)?.value);

  if (isProtected(pathname) && !hasToken) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(url);
  }

  // If user is signed in and hits /login, push them to /dashboard.
  if (pathname === "/login" && hasToken) {
    const url = req.nextUrl.clone();
    url.pathname = "/dashboard";
    url.search = "";
    return NextResponse.redirect(url);
  }

  const response = NextResponse.next();
  response.headers.set("Vary", "Cookie, Accept-Language");
  return response;
}

export const config = {
  matcher: [
    // Run on everything except static assets and image optimizer.
    "/((?!_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml).*)",
  ],
};
