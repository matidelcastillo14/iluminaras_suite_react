import api from './api';

export const getRecentCfes = async () => api.get('/cfe/auto/api/cfes');

export const pollCfesNow = async () => api.post('/cfe/auto/api/cfes/poll_now');
