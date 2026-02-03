/**
 * Frontend configuration
 * Uses environment variables set by Vite
 */

export const API_BASE_URL = import.meta?.env?.VITE_API_URL || 'http://localhost:3000';
