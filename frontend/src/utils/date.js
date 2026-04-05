/**
 * Utilities for date and time formatting. Uses the browser's locale
 * to produce human‑friendly strings. These helpers can be extended
 * as needed for more complex formatting.
 */

/**
 * Format a date string or Date instance into YYYY‑MM‑DD HH:mm:ss.
 * Returns an empty string if the input is falsy.
 *
 * @param {string|Date|null|undefined} value
 */
export function formatDateTime(value) {
  if (!value) return '';
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const pad = (n) => String(n).padStart(2, '0');
  const y = date.getFullYear();
  const m = pad(date.getMonth() + 1);
  const d = pad(date.getDate());
  const h = pad(date.getHours());
  const min = pad(date.getMinutes());
  const s = pad(date.getSeconds());
  return `${y}-${m}-${d} ${h}:${min}:${s}`;
}

/**
 * Format a date string or Date instance into YYYY‑MM‑DD.
 * Returns an empty string if the input is falsy.
 *
 * @param {string|Date|null|undefined} value
 */
export function formatDate(value) {
  if (!value) return '';
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const pad = (n) => String(n).padStart(2, '0');
  const y = date.getFullYear();
  const m = pad(date.getMonth() + 1);
  const d = pad(date.getDate());
  return `${y}-${m}-${d}`;
}