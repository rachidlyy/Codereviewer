/**
 * Clerk's prebuilt components, themed to the locked design system.
 *
 * Clerk renders its own components with its own stylesheet, so without this
 * the sign-in card arrives looking like a different product. The values below
 * reference the design tokens from `styles.css` (`:root`) rather than copying
 * literal colours, so the auth UI follows the design system instead of
 * drifting away from it.
 *
 * `design.md` is the source of truth for those tokens — read it before
 * changing anything here.
 */

export const clerkAppearance = {
  variables: {
    // --- brand ----------------------------------------------------------
    colorPrimary: 'var(--color-accent)',
    colorTextOnPrimaryBackground: 'var(--color-accent-ink)',

    // --- surfaces -------------------------------------------------------
    colorBackground: 'var(--color-paper-2)',
    colorInputBackground: 'var(--color-paper-3)',
    colorInputText: 'var(--color-ink)',

    // --- text -----------------------------------------------------------
    colorText: 'var(--color-ink)',
    colorTextSecondary: 'var(--color-ink-2)',

    // --- semantic -------------------------------------------------------
    colorDanger: 'var(--color-bad)',
    colorSuccess: 'var(--color-ok)',
    colorWarning: 'var(--color-warn)',

    // --- type + geometry ------------------------------------------------
    fontFamily: 'var(--font-body)',
    fontFamilyButtons: 'var(--font-display)',
    borderRadius: 'var(--radius-input)',
  },

  elements: {
    // Clerk nests two elements here: `.cl-cardBox` is the outer wrapper and
    // `.cl-card` the actual surface. Overriding only `card` leaves the
    // wrapper's default drop shadow visible as a halo around an otherwise
    // flat card — verified in the browser, not assumed. Both are flattened.
    cardBox: {
      boxShadow: 'none',
      borderRadius: 'var(--radius-card)',
    },
    card: {
      boxShadow: 'none',
      border: '1px solid var(--color-rule)',
      borderRadius: 'var(--radius-card)',
      backgroundColor: 'var(--color-paper-2)',
    },
    // The default header block duplicates what the app's own Header already
    // says, so the spacing is tightened rather than the content removed
    // (Clerk owns the text and it must stay accurate).
    headerTitle: {
      fontFamily: 'var(--font-display)',
      fontWeight: '500',
    },
    formButtonPrimary: {
      fontFamily: 'var(--font-display)',
      fontWeight: '500',
      boxShadow: 'none',
    },
    // Match the app's hairline borders so inputs sit in the same visual
    // system as the editor panel and problem cards.
    formFieldInput: {
      border: '1px solid var(--color-rule)',
      backgroundColor: 'var(--color-paper-3)',
    },
    socialButtonsBlockButton: {
      border: '1px solid var(--color-rule)',
    },
  },
};
