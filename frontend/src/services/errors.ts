/**
 * Shared error formatting for the route components.
 *
 * Lives here rather than in `api.ts` because it is presentation logic, not
 * transport: `api.ts` stays the only module that performs HTTP.
 */

import { ApiError } from './api';

/** Turn anything thrown by the API layer into a message we can display. */
export function messageOf(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return 'Something went wrong. Please try again.';
}
