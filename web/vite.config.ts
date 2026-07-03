import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Dev: Vite serves the UI with HMR and proxies /api to the FastAPI backend
// (python run_ui.py, port 8787). Prod: `npm run build` emits web/dist, which
// the backend serves directly — no Node process at runtime.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8787',
    },
  },
})
