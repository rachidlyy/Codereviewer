import { Show, UserButton } from '@clerk/react';
import { Code2 } from 'lucide-react';
import { Link, NavLink } from 'react-router-dom';

type Props = {
  /** Shows a small badge when the backend is running without an LLM key. */
  offlineReview?: boolean;
};

export default function Header({ offlineReview = false }: Props) {
  return (
    <header>
      <Link className="brand" to="/">
        <div className="logo">
          <Code2 size={18} />
        </div>
        <span>
          Code<b>Reviewer</b>
        </span>
      </Link>

      {/* `NavLink` sets `aria-current="page"` on the active route, which is
          what the underline in styles.css keys off — no extra state needed.

          History and Profile are signed-in only: both are scoped to the
          caller's own rows, so showing them to a visitor would offer a link
          straight to a redirect. */}
      <nav className="nav">
        <NavLink to="/" end>
          Home
        </NavLink>
        <NavLink to="/problems">Problems</NavLink>
        <Show when="signed-in">
          <NavLink to="/history">History</NavLink>
          <NavLink to="/profile">Profile</NavLink>
        </Show>
      </nav>

      <div className="header-right">
        {/* The "Python" pill and the "MVP Demo" chip were both removed. The
            language is still stated in the editor header, so dropping the pill
            loses no information. The offline badge stays: it is the only signal
            that reviews are rule-based rather than model-generated. */}
        {offlineReview && (
          <span className="mvp offline-badge" title="No LLM key configured — reviews are rule-based">
            Offline review
          </span>
        )}

        {/* Links to the real routes rather than Clerk's modals. The modal kept
            sign-in out of the URL, so a refresh lost the student's place and
            the flow could not be linked to or bookmarked. */}
        <Show when="signed-out">
          <Link className="ghost" to="/sign-in">
            Sign in
          </Link>
          <Link className="cta" to="/sign-up">
            Sign up
          </Link>
        </Show>
        <Show when="signed-in">
          <UserButton />
        </Show>
      </div>
    </header>
  );
}
