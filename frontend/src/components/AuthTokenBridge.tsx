import { useAuth } from '@clerk/react';
import { useEffect } from 'react';

import { setTokenGetter } from '../services/clerkToken';

/**
 * Hands Clerk's token getter to the API layer. Renders nothing.
 *
 * This has to be a component because `useAuth` is a hook and only works
 * inside the `ClerkProvider` tree, whereas `services/api.ts` is a plain
 * module. Mount it once, inside the provider, above anything that fetches.
 */
export default function AuthTokenBridge() {
  const { getToken, isLoaded } = useAuth();

  useEffect(() => {
    // Wait for Clerk to load, otherwise the first request would go out
    // without a token and be answered with a 401 even though the user is
    // signed in.
    if (!isLoaded) return;

    setTokenGetter(() => getToken());
    return () => setTokenGetter(null);
  }, [getToken, isLoaded]);

  return null;
}
