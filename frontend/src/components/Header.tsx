import { Code2 } from 'lucide-react';
import { Show, UserButton } from '@clerk/react';

type Props = {
  onHome: () => void;
  offlineReview?: boolean;
  onSignIn: () => void;
  onSignUp: () => void;
};

export default function Header({
  onHome,
  offlineReview = false,
  onSignIn,
  onSignUp,
}: Props) {
  return (
    <header>
      <div className="brand" onClick={onHome}>
        <div className="logo">
          <Code2 size={18} />
        </div>
        <span>
          Code<b>Reviewer</b>
        </span>
      </div>

      <nav className="header-right">
        <a className="nav-link" href="#about">About</a>
        <a className="nav-link" href="#progress">Progress</a>

        <Show when="signed-out">
          <button type="button" className="nav-link" onClick={onSignIn}>
            Sign in
          </button>
          <button
            type="button"
            className="nav-link nav-link-signin"
            onClick={onSignUp}
          >
            Create account
          </button>
        </Show>

        <Show when="signed-in">
          <UserButton />
        </Show>

        {offlineReview && (
          <span
            className="mvp offline-badge"
            title="No LLM key configured — reviews are rule-based"
          >
            Offline review
          </span>
        )}
      </nav>
    </header>
  );
}