import { SignUp } from '@clerk/react';

/**
 * Dedicated sign-up route.
 *
 * Mirrors `SignInPage`; see there for why Clerk's component is used rather than
 * a hand-built form. `routing="path"` requires the `/sign-up/*` route in
 * `App.tsx` so Clerk's verification steps get real sub-paths.
 */
export default function SignUpPage() {
  return (
    <section className="auth-page">
      <SignUp routing="path" path="/sign-up" signInUrl="/sign-in" />
    </section>
  );
}
