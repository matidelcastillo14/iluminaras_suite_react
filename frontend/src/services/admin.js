import api from './api';

// Service functions for the Admin module. These endpoints are
// hypothetical and must be implemented on the backend side. They
// correspond to existing web routes in the Flask blueprints but
// provide a JSON API for the React frontend.

/**
 * Retrieve a list of all users. Returns an array of user objects
 * containing id, username, email, first_name, last_name, phone,
 * attendance_ref_code, home_office_clock_enabled, role, is_active,
 * and created_at. The backend may also return additional fields as
 * necessary.
 */
export async function listUsers() {
  return await api.get('/admin/api/users');
}

/**
 * Fetch details for a single user by ID.
 * @param {number|string} id
 */
export async function getUser(id) {
  return await api.get(`/admin/api/users/${id}`);
}

/**
 * Create a new user.
 * Accepts an object with at least username, email, first_name,
 * last_name, role. The backend should generate a temporary password
 * and optionally send it via email. Returns the created user.
 *
 * @param {Object} payload
 */
export async function createUser(payload) {
  return await api.post('/admin/api/users', payload);
}

/**
 * Update an existing user.
 * Accepts a partial payload containing fields to update.
 *
 * @param {number|string} id
 * @param {Object} payload
 */
export async function updateUser(id, payload) {
  return await api.put(`/admin/api/users/${id}`, payload);
}

/**
 * Toggle a user's active status. Returns the updated user.
 * @param {number|string} id
 */
export async function toggleUser(id) {
  return await api.post(`/admin/api/users/${id}/toggle`);
}

/**
 * Reset a user's password to a temporary value. The backend
 * should return the new temporary password and optionally send it
 * via email. Returns an object containing `temp_password` and a
 * boolean `sent`.
 * @param {number|string} id
 */
export async function resetUserPassword(id) {
  return await api.post(`/admin/api/users/${id}/reset-temp`);
}

/**
 * List all available roles in the system. Returns an array of
 * strings.
 */
export async function listRoles() {
  return await api.get('/admin/api/roles');
}

/**
 * Fetch all application settings. Returns a dictionary of key/value
 * pairs.
 */
export async function listSettings() {
  return await api.get('/admin/api/settings');
}

/**
 * Update one or more settings. Accepts a dictionary of key/value
 * pairs and returns the updated settings.
 * @param {Object} payload
 */
export async function updateSettings(payload) {
  return await api.put('/admin/api/settings', payload);
}

/**
 * List all modules (internal and public) with their current enabled
 * status. Returns an array of objects: { key, name, description,
 * internal_enabled, public_enabled }.
 */
export async function listModules() {
  return await api.get('/admin/api/modules');
}

/**
 * Toggle a module's enabled state. Accepts the module key and a
 * boolean indicating whether it should be enabled or disabled.
 * @param {string} key
 * @param {{ internal?: boolean, public?: boolean }} payload
 */
export async function toggleModule(key, payload) {
  return await api.post(`/admin/api/modules/${key}/toggle`, payload);
}