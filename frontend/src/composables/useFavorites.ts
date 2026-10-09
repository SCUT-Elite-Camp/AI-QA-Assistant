import { ref } from 'vue'
import { createSharedComposable } from '@vueuse/core'
import { $fetch } from 'ofetch'

export const useFavorites = createSharedComposable(() => {
  const favoriteChats = ref<Array<{ id: string; label: string; to: string; lastFavoritedAt: string }>>([])
  const loading = ref(false)

  async function loadFavorites() {
    loading.value = true
    try {
      const data: any[] = await $fetch('/api/chats/favorites')
      favoriteChats.value = data.map(c => ({
        id: c.id,
        label: c.title || 'Untitled',
        to: `/chat/${c.id}`,
        lastFavoritedAt: c.lastFavoritedAt || c.updatedAt || ''
      }))
    } catch {
      favoriteChats.value = []
    } finally {
      loading.value = false
    }
  }

  /**
   * Call this after a favorite is toggled in any page.
   * If the favorites panel is open it will re-fetch automatically.
   */
  function notifyFavoriteChanged() {
    // Always reload so the panel stays fresh
    loadFavorites()
  }

  return { favoriteChats, loading, loadFavorites, notifyFavoriteChanged }
})
