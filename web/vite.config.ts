import { defineConfig } from 'vite'
import { nitro } from 'nitro/vite'
import vue from '@vitejs/plugin-vue'
import vueRouter from 'vue-router/vite'
import vueLayouts from 'vite-plugin-vue-layouts'
import vueDevtools from 'vite-plugin-vue-devtools'
import ui from '@nuxt/ui/vite'

import { fileURLToPath } from 'node:url'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    vueRouter({
      dts: fileURLToPath(new URL('./src/route-map.d.ts', import.meta.url))
    }),
    vueLayouts(),
    vue(),

    ui({
      prose: true,
      ui: {
        colors: {
          primary: 'blue',
          neutral: 'zinc'
        }
      }
    }),
    nitro({
      serverDir: './server',
      rollupConfig: {
        output: {
          chunkFileNames: chunk => `_chunks/${chunk.name.replace(/[\[\]]/g, '_')}-[hash].mjs`
        }
      }
    })
  ],
  server: {
    host: '0.0.0.0',
    port: 3000
  }
})

