<script setup lang="ts">
import { computed } from 'vue'
import { useHead } from '@unhead/vue'
import { useColorMode } from '@vueuse/core'

const colorMode = useColorMode()
const themeColor = computed(() => colorMode.value === 'dark' ? '#09090b' : '#fafafa')

useHead({
  meta: [
    { name: 'theme-color', content: themeColor }
  ]
})
</script>

<template>
  <UApp :toaster="{ position: 'top-right' }">
    <Suspense>
      <RouterView />
      <template #fallback>
        <main class="min-h-dvh flex items-center justify-center bg-default text-muted">
          <div role="status" class="flex items-center gap-3 text-sm">
            <UIcon name="i-lucide-loader-circle" class="size-5 animate-spin motion-reduce:animate-none" />
            <span>Loading workspace…</span>
          </div>
        </main>
      </template>
    </Suspense>
  </UApp>
</template>
