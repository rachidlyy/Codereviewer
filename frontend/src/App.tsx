import { useEffect, useState } from 'react';
import { Route, Routes } from 'react-router-dom';

import BeamsBackground from './components/BeamsBackground';
import Header from './components/Header';
import RequireAuth from './components/RequireAuth';
import HistoryRoute from './pages/HistoryRoute';
import HomeRoute from './pages/HomeRoute';
import NotFoundPage from './pages/NotFoundPage';
import ProblemsRoute from './pages/ProblemsRoute';
import ProfilePage from './pages/ProfilePage';
import SignInPage from './pages/SignInPage';
import SignUpPage from './pages/SignUpPage';
import SubmissionRoute from './pages/SubmissionRoute';
import WorkspaceRoute from './pages/WorkspaceRoute';
import { fetchHealth } from './services/api';

/**
 * Application shell.
 *
 * The shell is only responsible for the two things that are genuinely global:
 * the decorative background layer and the header. Everything below `<Routes>`
 * owns its own data.
 *
 * The routes are split by what each screen is *for* rather than by data source:
 * `/` answers "what should I do next?", `/problems` is the catalogue,
 * `/history` is the record, and `/profile` is the account. They used to share
 * one page, which meant the catalogue carried a marketing hero it did not need
 * and the home page had nowhere to put progress.
 */
export default function App() {
  // Whether reviews come from the model or the rule-based fallback. Purely
  // cosmetic, so a failure here is ignored rather than surfaced.
  const [offlineReview, setOfflineReview] = useState(false);

  useEffect(() => {
    fetchHealth()
      .then((health) => setOfflineReview(!health.llm_configured))
      .catch(() => undefined);
  }, []);

  return (
    <div className="app">
      {/* Decorative only. Sits in its own fixed layer so it never affects
          layout, and never receives a click. */}
      <BeamsBackground intensity="subtle" />

      <div className="app-content">
        <Header offlineReview={offlineReview} />

        <Routes>
          {/* Public: the pitch for a visitor, the dashboard for a student. */}
          <Route path="/" element={<HomeRoute />} />

          {/* Public: the catalogue is browsable before signing in. The
              workspace behind it is not. */}
          <Route path="/problems" element={<ProblemsRoute />} />

          {/* Gated: these need an account to mean anything. */}
          <Route
            path="/problems/:problemId"
            element={
              <RequireAuth>
                <WorkspaceRoute />
              </RequireAuth>
            }
          />
          <Route
            path="/history"
            element={
              <RequireAuth>
                <HistoryRoute />
              </RequireAuth>
            }
          />
          <Route
            path="/history/:submissionId"
            element={
              <RequireAuth>
                <SubmissionRoute />
              </RequireAuth>
            }
          />
          <Route
            path="/profile"
            element={
              <RequireAuth>
                <ProfilePage />
              </RequireAuth>
            }
          />

          {/* Clerk owns these. The trailing `*` is required by
              `routing="path"`, which pushes Clerk's own steps (MFA, password
              reset) onto real sub-paths. */}
          <Route path="/sign-in/*" element={<SignInPage />} />
          <Route path="/sign-up/*" element={<SignUpPage />} />

          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </div>
    </div>
  );
}
