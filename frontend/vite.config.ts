import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      // The dashboard calls relative /api/* URLs; Vite forwards them to FastAPI.
      '/api': { target: `http://127.0.0.1:${process.env.API_PORT ?? 8000}`, changeOrigin: true },
    },
  },
});
