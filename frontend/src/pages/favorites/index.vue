<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useFavorites } from '../../composables/useFavorites'

const router = useRouter()
const { favoriteChats, loading, loadFavorites } = useFavorites()

const searchQuery = ref('')

const filtered = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return favoriteChats.value
  return favoriteChats.value.filter(c => c.label.toLowerCase().includes(q))
})

onMounted(() => {
  loadFavorites()
})
</script>

<template>
  <UDashboardPanel id="favorites" class="min-h-0">
    <template #header>
      <div class="flex items-center gap-3 px-4 py-3 border-b border-default/50">
        <UIcon name="i-lucide-star" class="w-5 h-5 text-amber-400" />
        <h1 class="text-lg font-semibold text-highlighted">Favorites</h1>
        <span class="text-xs text-muted bg-accented/60 px-2 py-0.5 rounded-full">
          {{ favoriteChats.length }} saved
        </span>
        <div class="ms-auto w-64">
          <UInput
            v-model="searchQuery"
            placeholder="Search favorites..."
            icon="i-lucide-search"
            size="sm"
            variant="subtle"
            class="rounded-lg"
          />
        </div>
      </div>
    </template>

    <template #body>
      <UContainer class="py-8 max-w-4xl">
        <!-- Loading -->
        <div v-if="loading" class="flex justify-center py-20">
          <UIcon name="i-lucide-loader-2" class="w-8 h-8 text-muted animate-spin" />
        </div>

        <!-- Empty State -->
        <div
          v-else-if="!favoriteChats.length"
          class="flex flex-col items-center gap-4 py-24 text-center"
        >
          <div class="w-16 h-16 rounded-2xl bg-amber-400/10 flex items-center justify-center">
            <UIcon name="i-lucide-star" class="w-8 h-8 text-amber-400" />
          </div>
          <div>
            <p class="text-lg font-semibold text-highlighted">No favorites yet</p>
            <p class="text-sm text-muted mt-1">Star ★ any message in a conversation to save it here</p>
          </div>
          <UButton
            label="Go to chats"
            icon="i-lucide-message-circle"
            color="neutral"
            variant="outline"
            size="sm"
            class="rounded-full"
            @click="router.push('/')"
          />
        </div>

        <!-- No Search Results -->
        <div
          v-else-if="filtered.length === 0"
          class="flex flex-col items-center gap-3 py-16 text-center"
        >
          <UIcon name="i-lucide-search-x" class="w-8 h-8 text-muted" />
          <p class="text-sm text-muted">No results for "<span class="text-highlighted">{{ searchQuery }}</span>"</p>
        </div>

        <!-- Favorites Grid -->
        <div v-else class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <div
            v-for="chat in filtered"
            :key="chat.id"
            class="group relative rounded-2xl border border-default/40 bg-elevated/60 hover:bg-elevated hover:border-amber-400/40 hover:shadow-lg hover:shadow-amber-400/5 transition-all duration-200 cursor-pointer overflow-hidden"
            @click="router.push(chat.to)"
          >
            <!-- Top accent bar -->
            <div class="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-amber-400/0 via-amber-400/60 to-amber-400/0 opacity-0 group-hover:opacity-100 transition-opacity" />

            <div class="p-4 flex flex-col gap-3">
              <!-- Header -->
              <div class="flex items-start gap-3">
                <div class="w-8 h-8 rounded-xl bg-amber-400/10 flex items-center justify-center shrink-0 mt-0.5">
                  <UIcon name="i-lucide-star" class="w-4 h-4 text-amber-400" />
                </div>
                <div class="flex-1 min-w-0">
                  <p class="text-sm font-semibold text-highlighted truncate leading-snug">
                    {{ chat.label }}
                  </p>
                  <p v-if="chat.lastFavoritedAt" class="text-xs text-muted mt-0.5">
                    {{ new Date(chat.lastFavoritedAt).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) }}
                  </p>
                </div>
              </div>

              <!-- Footer -->
              <div class="flex items-center justify-between pt-1 border-t border-default/30">
                <span class="text-xs text-muted">Favorited conversation</span>
                <UIcon
                  name="i-lucide-arrow-right"
                  class="w-3.5 h-3.5 text-muted opacity-0 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all"
                />
              </div>
            </div>
          </div>
        </div>
      </UContainer>
    </template>
  </UDashboardPanel>
</template>
