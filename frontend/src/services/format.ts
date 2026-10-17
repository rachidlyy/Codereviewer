/**
 * Date formatting helpers.
 *
 * Shared because three screens now show timestamps from the same backend
 * field, and having each invent its own wording made the same run read
 * differently on the history list, the history detail and the profile.
 *
 * The backend sends ISO 8601 with a timezone offset, so `new Date()` parses it
 * correctly and the result can be rendered in the viewer's own locale.
 */

/** Full date, for a "member since" line. */
export function formatJoined(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
}

/**
 * Short date and time, for a history row.
 *
 * Deliberately absolute rather than "3 hours ago": the history is a record of
 * a session the student just had, and a relative label that silently drifts as
 * the page sits open is worse than a fixed timestamp.
 */
export function formatWhen(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}
