import { defineConfig } from 'vite'
import { nitro } from 'nitro/vite'
import vue from '@vitejs/plugin-vue'
import vueRouter from 'vue-router/vite'
import vueLayouts from 'vite-plugin-vue-layouts'
import vueDevtools from 'vite-plugin-vue-devtools'
import ui from '@nuxt/ui/vite'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    vueRouter({
      dts: 'src/route-map.d.ts'
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
      // Nitro 3 beta emits dynamic route names such as "[batch_id]" as a
      // Rollup filename pattern on Windows. Sanitize chunk names while still
      // retaining content hashes so attachment routes can be built safely.
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

