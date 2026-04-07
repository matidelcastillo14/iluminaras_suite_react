import api from './api';

/**
 * Servicio para interactuar con el backend del módulo CFE Auto.
 */

export const getCfeStatus = async () => {
  return await api.get('/api/cfe-auto/status');
};

export const forceCfeProcess = async () => {
  return await api.post('/api/cfe-auto/process');
};