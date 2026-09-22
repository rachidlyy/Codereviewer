import { SignIn } from '@clerk/react';

type Props = {
  onBack: () => void;
  onSwitchToSignUp: () => void;
};

export default function LoginPage({ onBack, onSwitchToSignUp }: Props) {
  return (
    <main className="auth-page">
      <button className="auth-back" type="button" onClick={onBack}>
        ← Back to problems
      </button>

      <div className="auth-card">
        <div className="auth-head">
          <h3>Welcome back</h3>
          <p>Sign in to save your progress and pick up where you left off.</p>
        </div>

        <div className="auth-clerk">
          <SignIn
            appearance={{
              variables: {
                colorPrimary: 'oklch(58% 0.19 265)',
                colorBackground: 'oklch(17% 0.006 265)',
                colorForeground: 'oklch(96% 0.004 265)',
                colorMutedForeground: 'oklch(74% 0.010 265)',
                colorInput: 'oklch(20% 0.008 265)',
                colorInputForeground: 'oklch(96% 0.004 265)',
                colorDanger: 'oklch(68% 0.15 25)',
                borderRadius: '8px',
                fontFamily:
                  "'Inter','Segoe UI',system-ui,-apple-system,sans-serif",
              },
              elements: {
                rootBox: {
                  width: '100%',
                  display: 'flex',
                  justifyContent: 'center',
                },
                card: {
                  background: 'transparent',
                  boxShadow: 'none',
                  border: 'none',
                  padding: 0,
                  width: '100%',
                  maxWidth: '100%',
                  margin: '0 auto',
                },
                headerTitle: { display: 'none' },
                headerSubtitle: { display: 'none' },
                socialButtonsBlockButton: {
                  background: 'oklch(20% 0.008 265)',
                  border: '1px solid oklch(26% 0.010 265)',
                  color: 'oklch(96% 0.004 265)',
                },
                formButtonPrimary: {
                  background: 'oklch(58% 0.19 265)',
                  color: 'oklch(14% 0.02 265)',
                  fontWeight: 500,
                },
                footerAction: { display: 'none' },
              },
            }}
          />
        </div>

        <p className="auth-alt">
          No account yet?{' '}
          <button type="button" className="auth-link" onClick={onSwitchToSignUp}>
            Create one
          </button>
        </p>
      </div>
    </main>
  );
}