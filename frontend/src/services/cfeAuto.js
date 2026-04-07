import api from './api';

export const getCfes = async () => api.get('/cfe/auto/api/cfes');

export const pollNow = async () => api.post('/cfe/auto/api/cfes/poll_now');
