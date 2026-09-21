/**
 * Bridge between Clerk (a React context) and the API layer (a plain module).
 *
 * `useAuth().getToken` is a hook, so `services/api.ts` cannot call it — hooks
 * only run inside a component. Instead a single `<AuthTokenBridge/>` component
 * registers the getter here when it mounts, and `api.ts` reads it while
 * building a request.
 *
 * This module deliberately lives beside `api.ts` rather than inside it: it
 * holds a function reference and performs no HTTP, which keeps `api.ts` the
 * only module that talks to the network.
 */

type TokenGetter = () => Promise<string | null>;

let tokenGetter: TokenGetter | null = null;

/** Called by `<AuthTokenBridge/>` on mount, and with `null` on unmount. */
export function setTokenGetter(getter: TokenGetter | null): void {
  tokenGetter = getter;
}

/**
 * Resolve the current Clerk session token.
 *
 * Returns `null` when signed out, or before Clerk has finished loading.
 * Clerk rejects `getToken()` in those states, so the failure is swallowed:
 * an anonymous request that the server answers with 401 is a clearer signal
 * than an unhandled rejection inside the fetch helper.
 */
export async function getSessionToken(): Promise<string | null> {
  if (!tokenGetter) return null;
  try {
    return await tokenGetter();
  } catch {
    return null;
  }
}
