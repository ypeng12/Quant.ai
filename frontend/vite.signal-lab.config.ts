import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5175,
    strictPort: true,
    proxy: {
      '/api/research/signal-lab': {
        target: process.env.SIGNAL_LAB_API_URL || 'http://127.0.0.1:8001',
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist-signal-lab',
    emptyOutDir: true,
    rollupOptions: {
      input: fileURLToPath(new URL('./signal-lab.html', import.meta.url)),
    },
  },
})
