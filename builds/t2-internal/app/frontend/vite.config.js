import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// /api is proxied to the FastAPI backend in dev; in prod set VITE_API_URL.
export default defineConfig({
  // relative base: built assets resolve correctly wherever the SPA is mounted
  // (eos serves it under /app/, not the domain root)
  base: './',
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
})
