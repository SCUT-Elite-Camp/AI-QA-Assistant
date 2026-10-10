import { defineConfig } from 'vite'
import { nitro } from 'nitro/vite'
import vue from '@vitejs/plugin-vue'
import vueRouter from 'vue-router/vite'
import vueLayouts from 'vite-plugin-vue-layouts'
import vueDevtools from 'vite-plugin-vue-devtools'
import ui from '@nuxt/ui/vite'

import { fileURLToPath } from 'node:url'

// https://vitejs.dev/config/
export default defineConfig(({ command }) => ({
  plugins: [
    vueRouter({
      dts: fileURLToPath(new URL('./src/route-map.d.ts', import.meta.url))
    }),
    vueLayouts(),
    vue(),

    ui({
      // Generate declarations in development; concurrent production bundles
      // must not race to overwrite the same files on Windows.
      dts: command === 'serve',
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
      ...(process.env.AI_QA_BUILD_DIR ? { output: { dir: process.env.AI_QA_BUILD_DIR } } : {}),
      // Route segments such as [id] must not become Rollup placeholders.
      rollupConfig: {
        output: {
          chunkFileNames: chunk => `chunks/${chunk.name.replace(/[^\w.-]/g, '_')}-[hash].mjs`
        }
      }
    })
  ],
  server: {
    fs: { allow: [fileURLToPath(new URL('.', import.meta.url)), fileURLToPath(new URL('./node_modules', import.meta.url))] },
    host: '0.0.0.0',
    port: 3000
  }
}))

