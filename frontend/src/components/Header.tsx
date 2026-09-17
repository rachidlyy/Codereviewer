import { Code2 } from 'lucide-react';

type Props = {
  onHome: () => void;
  /** Shows a small badge when the backend is running without an LLM key. */
  offlineReview?: boolean;
};

export default function Header({ onHome, offlineReview = false }: Props) {
  return (
    <header>
      <div className="brand" onClick={onHome}>
        <div className="logo">
          <Code2 size={18} />
        </div>
        <span>
          CodeMentor <b>AI</b>
        </span>
      </div>
      <div className="header-right">
        <span className="python-pill">● Python</span>
        {offlineReview && (
          <span className="mvp offline-badge" title="No LLM key configured — reviews are rule-based">
            Offline review
          </span>
        )}
        <span className="mvp">MVP Demo</span>
      </div>
    </header>
  );
}
