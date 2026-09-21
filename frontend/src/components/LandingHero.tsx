import { Link } from 'react-router-dom';

/** The four stages of the loop the whole product is built around. This is the
 *  feature stack: it explains the demo path rather than listing generic
 *  capabilities, which is the honest version of "what does this do". */
const STEPS = [
  {
    name: 'Problem',
    body: 'Pick a focused challenge with a written brief and worked examples.',
  },
  {
    name: 'Code',
    body: 'Write Python in a real editor, with starter code already in place.',
  },
  {
    name: 'Test',
    body: 'Run the actual test suite and see exactly which cases pass.',
  },
  {
    name: 'Review',
    body: 'Get scored feedback on correctness, readability and efficiency.',
  },
];

/** Static sample data for the hero proof panel. Deliberately illustrative, and
 *  labelled as such - it previews the real review output rather than inventing
 *  a screenshot of a run that never happened. */
const SAMPLE_SCORES = [
  { label: 'Correctness', value: 9 },
  { label: 'Readability', value: 8 },
  { label: 'Efficiency', value: 7 },
];

/**
 * The signed-out landing page.
 *
 * Split out of the catalogue when the routes were separated. `/` is now the
 * home page and `/problems` the full catalogue, so the pitch needed a home of
 * its own — and a student who is already signed in has no use for it, which is
 * why `HomeRoute` renders this only when nobody is.
 */
export default function LandingHero() {
  return (
    <>
      {/* Hero. Sized to complete inside the first viewport: headline,
          supporting line, CTA and proof panel all sit above the fold. */}
      <section className="hero">
        <h1>
          Sharpen your code.
          <br />
          <span>Understand why it works.</span>
        </h1>
        <p className="hero-copy">
          Solve focused coding problems, run real test cases, and get actionable feedback from an AI
          programming mentor.
        </p>
        <div className="hero-actions">
          {/* Was an in-page anchor to #catalogue. The catalogue is its own
              route now, so this is a real navigation. */}
          <Link className="cta" to="/problems">
            Browse problems
          </Link>
          {/* Was "No account, no setup — pick one and run it." That stopped
              being true in Phase 2: sign-in is now mandatory, and Clerk
              blocks the workspace until you have an account. Claiming
              otherwise on the landing page was the first thing a visitor
              would catch us out on. */}
          <span className="cta-note">Sign in to save your progress and submission history.</span>
        </div>

        <figure className="hero-proof">
          <div className="proof-head">
            <span>Sample AI review</span>
            <span className="proof-score">
              8<span>/10</span>
            </span>
          </div>
          <div className="proof-bars">
            {SAMPLE_SCORES.map((score) => (
              <div className="proof-bar" key={score.label}>
                <div>
                  <span>{score.label}</span>
                  <b>{score.value}/10</b>
                </div>
                <div className="proof-track">
                  <i style={{ width: `${score.value * 10}%` }} />
                </div>
              </div>
            ))}
          </div>
          <p className="proof-line">
            Your loop returns the right answer, but it re-scans the whole list on every pass.
          </p>
          <figcaption>A sample review, shown before you write a line.</figcaption>
        </figure>
      </section>

      <section className="steps">
        <h2>Four steps, one loop.</h2>
        <ol className="steps-list">
          {STEPS.map((step) => (
            <li key={step.name}>
              <b>{step.name}</b>
              <p>{step.body}</p>
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}
