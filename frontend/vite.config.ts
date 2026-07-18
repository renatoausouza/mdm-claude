import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// API path prefixes the backend actually owns (src/mdm/main.py's routers) —
// proxied to the FastAPI dev server so `npm run dev` works without CORS
// (the backend has no CORS middleware, matching how production's nginx
// reverse-proxies the same paths — see deploy/nginx-mdm.conf). Everything
// else falls through to Vite's own dev server for the SPA/client routing.
const API_PATHS = ['/documents', '/jobs', '/duplicates', '/master-records', '/auth', '/users', '/audit', '/health', '/ready']

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(
      API_PATHS.map((path) => [path, { target: 'http://127.0.0.1:8000', changeOrigin: true }]),
    ),
  },
})
