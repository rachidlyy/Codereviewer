import { useUser } from '@clerk/react';
import { useCallback, useEffect, useState } from 'react';

import LandingHero from '../components/LandingHero';
import HomePage from './HomePage';
import { fetchProgress } from '../services/api';
import { messageOf } from '../services/errors';
import type { Progress } from '../types';

/**
 * Route wrapper for `/`.
 *
 * Two screens behind one path: the pitch for a visitor, the dashboard for a
 * student. That split is deliberate — "sign-in is mandatory" was about the
 * demo path, not about hiding the landing page, and the hero's "sign in to
 * save your progress" line only makes sense somewhere a signed-out visitor
 * can actually read it.
 */
export default function HomeRoute() {
  const { isLoaded, isSignedIn, user } = useUser();

  const [progress, setProgress] = useState<Progress | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setProgress(await fetchProgress());
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Wait for Clerk before deciding anything. Firing the request early would
    // send it without a token - `AuthTokenBridge` only registers the getter
    // once the session is loaded - and the student would be told they are
    // signed out when they are not.
    if (!isLoaded) return;

    if (!isSignedIn) {
      // Nothing to fetch, and the landing page does not need it.
      setProgress(null);
      setError(null);
      setLoading(false);
      return;
    }

    void load();
  }, [isLoaded, isSignedIn, load]);

  // Held back until Clerk has answered, so the header does not jump and a
  // signed-in student never sees the pitch flash past.
  if (!isLoaded) {
    return (
      <section className="workspace-placeholder">
        <p className="muted">
          <span className="spinner" /> Loading…
        </p>
      </section>
    );
  }

  if (!isSignedIn) {
    return (
      <main className="problems-page">
        <LandingHero />
      </main>
    );
  }

  return (
    <HomePage
      name={user?.firstName ?? null}
      progress={progress}
      loading={loading}
      error={error}
      onRetry={load}
    />
  );
}
