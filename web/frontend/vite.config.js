import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

// Flask serves the built files under /static/, so every asset URL the build
// writes into index.html has to carry that prefix.
//
// 'npm run dev' is optional: it serves the page from this Mac and forwards the
// API calls to the web VM, so the frontend can be changed without running
// 'vagrant provision' after every edit.
export default defineConfig({
  plugins: [vue()],
  base: '/static/',
  // No build.outDir here: the web role passes --outDir so the bundle lands
  // directly in the directory Flask serves. Without it the default 'dist'
  // applies, which is what a local 'npm run build' produces.
  server: {
    proxy: {
      '/api': 'http://192.168.56.12:8000',
      '/report': 'http://192.168.56.12:8000',
      '/invalidate': 'http://192.168.56.12:8000',
    },
  },
});
