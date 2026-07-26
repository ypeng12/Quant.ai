// frontend/src/config.ts
// Automatically resolves backend API URL for local dev, Docker container, or deployed HF Space

let defaultApiBase = 'http://127.0.0.1:8000';

if (typeof window !== 'undefined') {
  if (window.location.port === '5173' || window.location.port === '3000') {
    defaultApiBase = 'http://127.0.0.1:8000';
  } else {
    // When served via FastAPI server or hosted Space
    defaultApiBase = window.location.origin;
  }
}

export const API_BASE = (import.meta.env?.VITE_API_BASE as string) || defaultApiBase;
