import api from './api';

// Service functions for the Reloj Home Office (home office clock) module.
// The endpoints used here are not present in the legacy backend but should
// be implemented as part of the new API. They will allow the
// frontend to fetch the current snapshot and queue new marks without
// page reloads.

/**
 * Get the current snapshot for the logged‑in user. The response
 * should include fields: enabled (bool), module_enabled (bool),
 * has_ref_code (bool), ref_code (string), last_event_ts (ISO
 * string), last_event_state (string), last_event_error (string),
 * last_event_source (string). See app/services/home_office_clock.py.
 */
export async function getSnapshot() {
  return await api.get('/reloj_home_office/api/snapshot');
}

/**
 * Queue a new mark for the current user. The backend should return
 * an object containing `ok` (boolean) and `msg` (string) describing
 * the result. A 200 status with ok=false means the user is not
 * enabled or there was an error.
 */
export async function mark() {
  return await api.post('/reloj_home_office/api/marcar');
}