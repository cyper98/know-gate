/**
 * Public entry for the API client. Re-exports everything from the typed
 * resources and the `ApiError` / `NetworkError` classes so the rest of
 * the app only needs to import from `@/lib/api`.
 */

export * from "./api-types";
export * from "./api-client";
