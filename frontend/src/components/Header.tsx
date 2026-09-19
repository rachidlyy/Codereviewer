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
          Code<b>Reviewer</b>
        </span>
      </div>
      {/* The "Python" pill and the "MVP Demo" chip were both removed. The
          language is still stated in the editor header, so dropping the pill
          loses no information. The offline badge stays: it is the only signal
          that reviews are rule-based rather than model-generated. */}
      {offlineReview && (
        <div className="header-right">
          <span className="mvp offline-badge" title="No LLM key configured — reviews are rule-based">
            Offline review
          </span>
        </div>
      )}
    </header>
  );
}
