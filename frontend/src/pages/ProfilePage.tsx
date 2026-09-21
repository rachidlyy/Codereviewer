import { UserProfile, useUser } from '@clerk/react';
import { useEffect, useState } from 'react';

import { fetchMe } from '../services/api';
import { messageOf } from '../services/errors';
import { formatJoined } from '../services/format';
import type { User } from '../types';

/**
 * The student's profile.
 *
 * Two halves, deliberately. The top card is CodeReviewer's own record — the
 * row runs and reviews are attached to — and it is read-only, because editing
 * it here would mean duplicating identity state that Clerk already owns. The
 * bottom half is Clerk's own `<UserProfile/>`, which handles the things that
 * genuinely need writing (name, email, password, active sessions). Building
 * that by hand would mean handling credentials ourselves for no gain.
 */
export default function ProfilePage() {
  const { user: clerkUser } = useUser();
  const [record, setRecord] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Guards against a response landing after the student has navigated away.
    let cancelled = false;

    fetchMe()
      .then((me) => {
        if (!cancelled) setRecord(me);
      })
      .catch((err) => {
        if (!cancelled) setError(messageOf(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  // Clerk already has this client-side, so it renders immediately while the
  // local row is still in flight.
  const email = clerkUser?.primaryEmailAddress?.emailAddress ?? null;

  return (
    <main className="profile-page">
      <div className="profile-head">
        <h1>Your profile</h1>
        <p className="muted">{email ?? 'Signed in with Clerk'}</p>
      </div>

      <section className="profile-card">
        <h2>Account record</h2>
        <p className="muted">
          CodeReviewer keeps one local row per account so runs and reviews can be attributed to
          you. Clerk stays the source of truth for your identity.
        </p>

        {loading && (
          <p className="muted profile-status">
            <span className="spinner" /> Loading…
          </p>
        )}

        {!loading && error && <p className="profile-error">{error}</p>}

        {!loading && record && (
          <dl className="profile-grid">
            <div>
              <dt>Display name</dt>
              <dd>{record.display_name ?? '—'}</dd>
            </div>
            <div>
              <dt>Email</dt>
              <dd>{record.email ?? '—'}</dd>
            </div>
            <div>
              <dt>Member since</dt>
              <dd>{formatJoined(record.created_at)}</dd>
            </div>
            <div>
              <dt>Clerk user id</dt>
              <dd className="mono">{record.clerk_user_id}</dd>
            </div>
          </dl>
        )}
      </section>

      <section className="profile-manage">
        <h2>Manage your account</h2>
        <UserProfile />
      </section>
    </main>
  );
}
