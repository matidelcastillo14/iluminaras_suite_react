import api from './api';

// Service functions for the Puerta (door control) module.
// The endpoints referenced here map closely to the existing routes
// in the backend blueprint. Only the health endpoint does not
// currently exist in the server; it should be added as described in
// the BACKEND_FALTANTE section.

/**
 * Retrieve the status/health information from the door controller.
 * Returns a JSON object with details such as API version, uptime or
 * other diagnostics. If not available the promise will reject.
 */
export async function getHealth() {
  return await api.get('/puerta/api/health');
}

/**
 * Send a command to open the door.
 * Returns the controller response (should include ok flag and msg).
 */
export async function openDoor() {
  return await api.post('/puerta/open');
}

/**
 * Raise the shutter fully.
 */
export async function shutterUp() {
  return await api.post('/puerta/shutter/up');
}

/**
 * Lower the shutter fully.
 */
export async function shutterDown() {
  return await api.post('/puerta/shutter/down');
}

/**
 * Stop the shutter movement.
 */
export async function shutterStop() {
  return await api.post('/puerta/shutter/stop');
}