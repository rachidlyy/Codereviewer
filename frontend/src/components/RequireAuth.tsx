import { useAuth } from '@clerk/react';
import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';

type Props = {
  children: ReactNode;
};

/**
 * Gate for the routes that need a signed-in user.
 *
 * The catalogue at `/` deliberately stays public: it is the landing page, and
 * an anonymous visitor needs somewhere to arrive before signing in. The
 * workspace and profile are gated because Phase 2 made runs and reviews belong
 * to an account — there is genuinely nothing to show without one.
 */
export default function RequireAuth({ children }: Props) {
  const { isLoaded, isSignedIn } = useAuth();
  const location = useLocation();

  // `isLoaded` is false until Clerk has finished restoring the session from
  // storage. Redirecting before then would bounce a signed-in student who
  // simply refreshed the page.
  if (!isLoaded) {
    return (
      <section className="workspace-placeholder">
        <span className="spinner" />
        <p className="muted">Checking your session…</p>
      </section>
    );
  }

  if (!isSignedIn) {
    // The path travels with the redirect so sign-in can send the student back
    // to the problem they actually clicked, rather than the catalogue.
    return <Navigate to="/sign-in" replace state={{ from: location.pathname }} />;
  }

  return <>{children}</>;
}
