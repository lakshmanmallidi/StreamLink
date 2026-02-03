import { API_BASE_URL } from "./config";

function logoutAndRedirect(message) {
  try {
    localStorage.removeItem("access_token");
    localStorage.removeItem("user");
    localStorage.removeItem("id_token");
  } catch {}
  const reason = message ? `?reason=${encodeURIComponent(message)}` : "";
  window.location.href = `/login${reason}`;
}

export async function apiFetch(path, options = {}) {
  const url = `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
  const token = localStorage.getItem("access_token");
  const headers = new Headers(options.headers || {});
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const opts = { ...options, headers };
  const response = await fetch(url, opts);

  if (response.status === 401 || response.status === 403) {
    // Token expired or invalid: force logout
    logoutAndRedirect("session_expired");
    // Return a rejected promise to stop caller flow
    throw new Error("Unauthorized");
  }

  return response;
}
