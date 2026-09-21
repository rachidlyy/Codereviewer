import { SignIn } from '@clerk/react';
import { useLocation } from 'react-router-dom';

/**
 * Dedicated sign-in route.
 *
 * This is Clerk's own component rather than a hand-built form — Clerk owns
 * password storage and verification, so a custom form would mean handling
 * credentials ourselves for no gain. `routing="path"` lets Clerk push its
 * internal steps (MFA, forgotten password) onto real sub-paths, which is why
 * the route is declared as `/sign-in/*` in `App.tsx`.
 */
export default function SignInPage() {
  const location = useLocation();

  // Set by `RequireAuth` when it bounced an anonymous visitor away from a
  // problem. Without this they would land on the catalogue after signing in
  // and have to find the problem again.
  const from = (location.state as { from?: string } | null)?.from ?? '/';

  return (
    <section className="auth-page">
      <SignIn
        routing="path"
        path="/sign-in"
        signUpUrl="/sign-up"
        fallbackRedirectUrl={from}
      />
    </section>
  );
}
