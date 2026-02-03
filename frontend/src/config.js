/**
 * Frontend configuration
 * Uses environment variables set by Vite
 */

// Prefer VITE_API_URL; otherwise, if running Parcel on 3001, default to backend on 3000
export const API_BASE_URL =
	(import.meta?.env?.VITE_API_URL)
	?? (typeof window !== "undefined" && window.location && window.location.port === "3001"
				? `${window.location.protocol}//${window.location.hostname}:3000`
				: window.location.origin);
