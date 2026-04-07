import axios from "axios";

export const API_BASE_URL =
  process.env.REACT_APP_API_BASE_URL ||
  process.env.REACT_APP_API_URL ||
  "http://localhost:5914";

const api = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
  headers: {
    Accept: "application/json",
    "Content-Type": "application/json",
  },
});

api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const payload = error?.response?.data;
    const normalized = new Error(
      payload?.detail || payload?.error || error.message || "Error de comunicación con el servidor"
    );
    normalized.status = error?.response?.status;
    normalized.data = payload;
    normalized.original = error;
    return Promise.reject(normalized);
  }
);

export const buildApiUrl = (relativeUrl = "") => {
  if (!relativeUrl) return API_BASE_URL;
  if (/^https?:\/\//i.test(relativeUrl)) return relativeUrl;
  return `${API_BASE_URL}${relativeUrl.startsWith("/") ? "" : "/"}${relativeUrl}`;
};

export const downloadFile = async (relativeUrl, filename = "archivo.pdf") => {
  const url = buildApiUrl(relativeUrl);
  const response = await axios.get(url, {
    withCredentials: true,
    responseType: "blob",
  });

  const blobUrl = window.URL.createObjectURL(new Blob([response.data]));
  const link = document.createElement("a");
  link.href = blobUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(blobUrl);
};

export default api;
