import { ClerkProvider } from '@clerk/react';
import React from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, useNavigate } from 'react-router-dom';

import { clerkAppearance } from './clerkAppearance';
import AuthTokenBridge from './components/AuthTokenBridge';
import App from './App';
import './styles.css';

/**
 * Clerk, mounted inside the router.
 *
 * `ClerkProvider` takes navigation as props (`routerPush` / `routerReplace`),
 * but it can only be handed a `useNavigate` from a component that is itself
 * inside the router — hence this wrapper rather than inline props. Without it
 * Clerk does a full page reload after sign-in, which throws away the SPA state
 * and makes the redirect noticeably slower.
 */
function ClerkRouterBridge() {
  const navigate = useNavigate();

  return (
    <ClerkProvider
      appearance={clerkAppearance}
      afterSignOutUrl="/"
      routerPush={(to) => navigate(to)}
      routerReplace={(to) => navigate(to, { replace: true })}
    >
      {/* Renders nothing; hands Clerk's token getter to services/api.ts. */}
      <AuthTokenBridge />
      <App />
    </ClerkProvider>
  );
}

// `clerk init` left this file as a single minified line. It is written out
// readably here because adding auth and routing made it too dense to follow.
// The other minified file in the project (styles.css line 2) is untouched.
createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ClerkRouterBridge />
    </BrowserRouter>
  </React.StrictMode>,
);
