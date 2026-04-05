// API helper module for React frontend.
// Uses Fetch API with credentials included to support session cookies.

const API_BASE_URL = process.env.REACT_APP_API_BASE_URL || 'http://localhost:5914';

export { API_BASE_URL };

function buildHeaders(options) {
  const headers = { ...(options.headers || {}) };
  const token = localStorage.getItem('access_token');
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const hasBody = typeof options.body !== 'undefined' && options.body !== null;
  if (hasBody && !(options.body instanceof FormData) && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }
  return headers;
}

async function request(path, options = {}) {
  const { responseType = 'auto', ...fetchOptions } = options;
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...fetchOptions,
    headers: buildHeaders(fetchOptions),
    credentials: 'include',
    body:
      fetchOptions.body instanceof FormData
        ? fetchOptions.body
        : typeof fetchOptions.body !== 'undefined' && fetchOptions.body !== null
        ? JSON.stringify(fetchOptions.body)
        : undefined,
  });

  const contentType = response.headers.get('content-type') || '';

  if (!response.ok) {
    let errorText = `HTTP ${response.status}`;
    try {
      if (contentType.includes('application/json')) {
        const data = await response.json();
        errorText = data.detail || data.error || data.msg || JSON.stringify(data);
      } else {
        errorText = await response.text();
      }
    } catch (e) {
      // keep default
    }
    throw new Error(errorText || `HTTP ${response.status}`);
  }

  if (responseType === 'blob') {
    const blob = await response.blob();
    const cd = response.headers.get('content-disposition') || '';
    let filename = '';
    const m = cd.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i);
    if (m) {
      filename = decodeURIComponent(m[1] || m[2] || '');
    }
    return { blob, filename, contentType };
  }

  if (responseType === 'text') {
    return await response.text();
  }

  if (responseType === 'json') {
    return await response.json();
  }

  if (contentType.includes('application/json')) {
    return await response.json();
  }
  return await response.text();
}

const api = {
  get: (path) => request(path, { method: 'GET' }),
  post: (path, body, options = {}) => request(path, { method: 'POST', body, ...options }),
  put: (path, body, options = {}) => request(path, { method: 'PUT', body, ...options }),
  delete: (path, options = {}) => request(path, { method: 'DELETE', ...options }),
  download: (path, options = {}) => request(path, { ...options, responseType: 'blob' }),
};

export default api;
