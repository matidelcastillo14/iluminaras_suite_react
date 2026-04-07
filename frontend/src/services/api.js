export const API_BASE_URL =
  process.env.REACT_APP_API_URL ||
  process.env.REACT_APP_API_BASE_URL ||
  'http://localhost:5914';

class ApiError extends Error {
  constructor(message, status = 0, data = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

const buildHeaders = (body, extraHeaders = {}) => {
  const headers = { Accept: 'application/json', ...extraHeaders };

  if (!(body instanceof FormData) && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  return headers;
};

const buildBody = (body) => {
  if (body == null) return undefined;
  if (body instanceof FormData) return body;
  return JSON.stringify(body);
};

const parseResponse = async (response) => {
  const contentType = response.headers.get('content-type') || '';

  if (contentType.includes('application/json')) {
    return response.json();
  }

  if (contentType.includes('text/')) {
    return response.text();
  }

  if (response.status === 204) {
    return null;
  }

  return response.blob();
};

const request = async (method, url, body, options = {}) => {
  const response = await fetch(`${API_BASE_URL}${url}`, {
    method,
    credentials: 'include',
    headers: buildHeaders(body, options.headers || {}),
    body: buildBody(body),
  });

  const data = await parseResponse(response);

  if (!response.ok) {
    const message =
      (data && (data.detail || data.error || data.message)) ||
      `HTTP ${response.status}`;
    throw new ApiError(message, response.status, data);
  }

  return data;
};

const api = {
  get: (url, options) => request('GET', url, undefined, options),
  post: (url, body, options) => request('POST', url, body, options),
  put: (url, body, options) => request('PUT', url, body, options),
  delete: (url, options) => request('DELETE', url, undefined, options),
};

export { ApiError };
export default api;
