import type { defineShortcuts as defineShortcutsFn } from '@nuxt/ui/dist/runtime/composables/defineShortcuts'
import type { useOverlay as useOverlayFn } from '@nuxt/ui/dist/runtime/composables/useOverlay'
import type { useToast as useToastFn } from '@nuxt/ui/dist/runtime/composables/useToast'

declare global {
  const defineShortcuts: typeof defineShortcutsFn
  const useOverlay: typeof useOverlayFn
  const useToast: typeof useToastFn
  const useAppConfig: () => {
    ui: {
      colors: {
        primary: string
        neutral: string
      }
    }
  }
}

export {}
