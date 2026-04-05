import api from './api';

// Service functions for the Postulaciones (job applications) module.
// These functions wrap the generic API helper and expose a clear
// contract to the UI layer. Most endpoints referenced here do not
// exist in the current backend; they are documented for future
// implementation in the BACKEND_FALTANTE section.

/**
 * Fetch a list of job applications.
 * Accepts optional search parameters. Returns an object containing
 * `applications` (array of application objects), `positions`
 * (available job positions), and `statuses` (allowed status values).
 *
 * @param {{ q?: string, positionId?: string|number, status?: string }} params
 */
export async function listApplications(params = {}) {
  const query = new URLSearchParams();
  if (params.q) query.append('q', params.q);
  if (params.positionId) query.append('position_id', params.positionId);
  if (params.status) query.append('status', params.status);
  const res = await api.get(`/postulaciones_admin/api/applications?${query.toString()}`);
  return res;
}

/**
 * Fetch details for a single application.
 *
 * @param {number|string} id application ID
 */
export async function getApplication(id) {
  return await api.get(`/postulaciones_admin/api/applications/${id}`);
}

/**
 * Update an existing application.
 *
 * Accepts a payload with fields to update (status, admin_note,
 * position_id). Returns the updated application.
 *
 * @param {number|string} id application ID
 * @param {Object} payload
 */
export async function updateApplication(id, payload) {
  return await api.put(`/postulaciones_admin/api/applications/${id}`, payload);
}

/**
 * Retrieve all job positions (puestos) sorted by sort_order and name.
 */
export async function listPositions() {
  return await api.get('/postulaciones_admin/api/positions');
}

/**
 * Create a new job position.
 * @param {{ name: string, sort_order?: number }} payload
 */
export async function createPosition(payload) {
  return await api.post('/postulaciones_admin/api/positions', payload);
}

/**
 * Update an existing job position.
 * Accepts a partial payload (name, sort_order, is_active).
 *
 * @param {number|string} id position ID
 * @param {Object} payload
 */
export async function updatePosition(id, payload) {
  return await api.put(`/postulaciones_admin/api/positions/${id}`, payload);
}

/**
 * Toggle active/inactive for a position.
 *
 * @param {number|string} id position ID
 */
export async function togglePosition(id) {
  return await api.post(`/postulaciones_admin/api/positions/${id}/toggle`);
}

/**
 * Permanently delete a position.
 *
 * @param {number|string} id position ID
 */
export async function deletePosition(id) {
  return await api.delete(`/postulaciones_admin/api/positions/${id}`);
}