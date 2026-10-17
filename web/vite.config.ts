import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The Python server owns the light; in development Vite proxies to it.
const server = 'http://127.0.0.1:8787'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/ws': { target: server, ws: true },
      '/api': server,
    },
  },
})
