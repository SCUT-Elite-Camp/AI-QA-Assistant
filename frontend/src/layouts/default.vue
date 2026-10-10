<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { $fetch } from 'ofetch'
import type { DropdownMenuItem } from '@nuxt/ui'
import { defineShortcuts, useToast } from '@nuxt/ui/composables'
import { useChats } from '../composables/useChats'
import { useUserSession } from '../composables/useUserSession'
import { useChatActions } from '../composables/useChatActions'
import { useCsrf } from '../composables/useCsrf'
import ModalSelectTopic from '../components/ModalSelectTopic.vue'
import ModalSettings from '../components/ModalSettings.vue'

const router = useRouter()
const route = useRoute()
const { loggedIn, fetchSession } = useUserSession()

const showSettingsModal = ref(false)
const { chats, groups, fetchChats } = useChats()
const { renameChat, deleteChat, createTopicForChat, addChatToTopic } = useChatActions()
const { csrf, headerName } = useCsrf()

fetchSession().catch(() => {})
fetchChats().catch(() => {})

const topics = ref<any[]>([])
async function loadTopics() {
  try {
    topics.value = await $fetch('/api/topics')
  } catch {
    topics.value = []
  }
}
loadTopics().catch(() => {})

const sidebarOpen = ref(false)
const sidebarCollapsed = ref(true)
const searchOpen = ref(false)
// Track which topics are expanded in the sidebar
const expandedTopics = ref<Set<string>>(new Set())

// Drag and drop state
const draggedChatId = ref<string | null>(null)
const dragOverTopicId = ref<string | null>(null)

// Topic selection modal state
const showSelectTopicModal = ref(false)
const targetChatIdForTopicModal = ref<string | null>(null)

watch(loggedIn, () => {
  fetchChats()
  loadTopics()
  sidebarOpen.value = false
})

// Auto-expand topic if current route chat belongs to that topic
watch(() => [route.path, chats.value], () => {
  const currentChatId = (route.params as { id?: string }).id
  if (currentChatId && chats.value.length) {
    const chat = chats.value.find(c => c.id === currentChatId)
    if (chat && (chat as any).topicId) {
      expandedTopics.value.add((chat as any).topicId)
      expandedTopics.value = new Set(expandedTopics.value)
    }
  }
}, { immediate: true, deep: true })

function toggleTopic(topicId: string) {
  if (expandedTopics.value.has(topicId)) {
    expandedTopics.value.delete(topicId)
  } else {
    expandedTopics.value.add(topicId)
  }
  // Force reactivity
  expandedTopics.value = new Set(expandedTopics.value)
}

// Get all chats belonging to a topic (filtered from already-loaded chats)
function getTopicChats(topicId: string) {
  return chats.value.filter(c => (c as any).topicId === topicId)
}

// Non-topic chats (standalone)
const standaloneChats = computed(() =>
  chats.value.filter(c => !(c as any).topicId)
)

async function createChatInTopic(topicId: string) {
  try {
    const newChat: any = await $fetch(`/api/topics/${topicId}/chats`, {
      method: 'POST',
      headers: { [headerName]: csrf() }
    })
    await fetchChats()
    // Make sure topic is expanded
    expandedTopics.value = new Set([...expandedTopics.value, topicId])
    router.push(`/chat/${newChat.id}`)
  } catch (err: any) {
    useToast().add({ title: 'Failed to create chat', description: err.message, color: 'error' })
  }
}

// Drag & Drop event handlers
function handleDragStart(chatId: string, event: DragEvent) {
  draggedChatId.value = chatId
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', chatId)
  }
}

function handleDragOver(topicId: string, event: DragEvent) {
  event.preventDefault()
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = 'move'
  }
  dragOverTopicId.value = topicId
}

function handleDragLeave(topicId: string) {
  if (dragOverTopicId.value === topicId) {
    dragOverTopicId.value = null
  }
}

async function handleDropOnTopic(topicId: string, event: DragEvent) {
  event.preventDefault()
  const chatId = draggedChatId.value || event.dataTransfer?.getData('text/plain')
  dragOverTopicId.value = null
  draggedChatId.value = null

  if (chatId && topicId) {
    await addChatToTopic(chatId, topicId)
    await fetchChats()
    expandedTopics.value = new Set([...expandedTopics.value, topicId])
  }
}

const dragOverStandalone = ref(false)

function handleDragOverStandalone(event: DragEvent) {
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  dragOverStandalone.value = true
}

function handleDragLeaveStandalone() {
  dragOverStandalone.value = false
}

async function handleDropOnStandalone(event: DragEvent) {
  event.preventDefault()
  const chatId = draggedChatId.value || event.dataTransfer?.getData('text/plain')
  dragOverStandalone.value = false
  draggedChatId.value = null

  if (chatId) {
    await addChatToTopic(chatId, null)
    await fetchChats()
  }
}

// Modal for "Add to Topic"
function openSelectTopicModal(chatId: string) {
  targetChatIdForTopicModal.value = chatId
  showSelectTopicModal.value = true
}

async function handleSelectTopicForChat(topicId: string) {
  if (targetChatIdForTopicModal.value && topicId) {
    await addChatToTopic(targetChatIdForTopicModal.value, topicId)
    await fetchChats()
    expandedTopics.value = new Set([...expandedTopics.value, topicId])
    targetChatIdForTopicModal.value = null
  }
}

function getChatActions(item: { id: string, label: string, topicId?: string | null }): DropdownMenuItem[][] {
  const isTopicChat = !!item.topicId
  const topicMenuItem = isTopicChat
    ? {
        label: 'Remove from Topic',
        icon: 'i-heroicons-folder-minus',
        onSelect: async () => {
          await addChatToTopic(item.id, null)
          await fetchChats()
        }
      }
    : {
        label: 'Add to Topic',
        icon: 'i-heroicons-folder-plus',
        onSelect: () => openSelectTopicModal(item.id)
      }

  return [[
    topicMenuItem,
    {
      label: 'Topic',
      icon: 'i-heroicons-sparkles',
      onSelect: async () => {
        const topic = await createTopicForChat(item.id)
        if (topic?.id) {
          await loadTopics()
          await fetchChats()
          expandedTopics.value = new Set([...expandedTopics.value, topic.id])
        }
      }
    },
    {
      label: 'Rename',
      icon: 'i-lucide-pencil',
      onSelect: () => renameChat(item.id, item.label === 'Untitled' ? '' : item.label)
    }
  ], [
    {
      label: 'Delete',
      icon: 'i-lucide-trash',
      color: 'error' as const,
      onSelect: () => deleteChat(item.id)
    }
  ]]
}

// Items for search and nav (all chats flat)
const searchGroups = computed(() => groups.value)

defineShortcuts({
  meta_o: () => {
    router.push('/')
  }
})
</script>

<template>
  <UDashboardGroup unit="rem">
    <UDashboardSidebar
      id="default"
      v-model:open="sidebarOpen"
      v-model:collapsed="sidebarCollapsed"
      :min-size="14"
      collapsible
      resizable
      class="border-r-0 py-4"
    >
      <template #header="{ collapsed }">
        <div class="flex items-center justify-between w-full h-8 min-h-[32px]">
          <ULink
            v-if="!collapsed"
            to="/"
            class="flex items-center gap-1 min-w-0"
          >
            <span class="text-xl font-bold tracking-tight text-highlighted leading-none select-none">Chat</span>
          </ULink>

          <div :class="[collapsed ? 'w-full flex items-center justify-center' : 'ms-auto flex items-center shrink-0']">
            <UDashboardSidebarCollapse class="shrink-0" />
          </div>
        </div>
      </template>

      <template #default="{ collapsed }">
        <UNavigationMenu
          :items="[{
            label: 'New chat',
            to: '/',
            kbds: ['meta', 'o'],
            icon: 'i-lucide-circle-plus'
          }, {
            label: 'Search',
            icon: 'i-lucide-search',
            kbds: ['meta', 'k'],
            onSelect: () => { searchOpen = true }
          }, {
            label: 'Topics',
            to: '/topics',
            icon: 'i-heroicons-squares-2x2'
          }, {
            label: 'Library',
            to: '/library',
            icon: 'i-lucide-library'
          }, {
            label: 'Favorites',
            to: '/favorites',
            icon: 'i-lucide-star'
          }]"
          :collapsed="collapsed"
          :ui="{
            link: collapsed
              ? 'py-2.5 px-0 justify-center rounded-xl'
              : 'text-[15px] sm:text-base py-2.5 px-3 gap-3.5 font-medium rounded-xl',
            linkLeadingIcon: 'size-5.5 min-w-[22px] min-h-[22px]'
          }"
          orientation="vertical"
        >
          <template #item-trailing="{ item }">
            <div
              v-if="item.kbds?.length"
              class="flex items-center gap-px opacity-0 group-hover:opacity-100 transition-opacity"
            >
              <UKbd
                v-for="kbd in item.kbds"
                :key="kbd"
                :value="kbd"
                size="md"
                variant="soft"
                class="bg-accented/50 text-xs"
              />
            </div>
          </template>
        </UNavigationMenu>

        <!-- Sidebar chat list (custom, not UNavigationMenu) -->
        <div v-if="!collapsed" class="flex-1 overflow-y-auto min-h-0 mt-2 px-1.5 space-y-1">

          <!-- Topic Groups (collapsible & drop targets) -->
          <template v-if="topics.length">
            <p class="text-xs font-semibold text-muted uppercase tracking-wider px-2.5 pt-4 pb-1.5">Topics</p>
            <div v-for="topic in topics" :key="topic.id" class="space-y-1">
              <!-- Topic header row (Drop target for dragging chats) -->
              <div
                class="group flex items-center gap-2 rounded-xl px-2.5 py-2 hover:bg-accented/50 cursor-pointer transition-all"
                :class="{ 'ring-2 ring-zinc-400 dark:ring-zinc-600 bg-zinc-500/10': dragOverTopicId === topic.id }"
                @click="toggleTopic(topic.id)"
                @dragover.prevent="handleDragOver(topic.id, $event)"
                @dragleave="handleDragLeave(topic.id)"
                @drop.prevent="handleDropOnTopic(topic.id, $event)"
              >
                <!-- Expand/collapse chevron -->
                <UIcon
                  :name="expandedTopics.has(topic.id) ? 'i-lucide-chevron-down' : 'i-lucide-chevron-right'"
                  class="w-4.5 h-4.5 text-muted shrink-0 transition-transform"
                />
                <span class="flex-1 truncate font-medium text-highlighted text-sm sm:text-[15px]">
                  {{ topic.title || 'Untitled Topic' }}
                </span>

                <!-- "+" button: add chat to this topic -->
                <UButton
                  icon="i-lucide-plus"
                  color="neutral"
                  variant="ghost"
                  size="sm"
                  class="opacity-0 group-hover:opacity-100 transition-opacity shrink-0 rounded-lg"
                  aria-label="Create chat in this topic"
                  @click.stop="createChatInTopic(topic.id)"
                />
              </div>

              <!-- Topic child chats (shown when expanded, Draggable) -->
              <template v-if="expandedTopics.has(topic.id)">
                <div
                  v-for="chat in getTopicChats(topic.id)"
                  :key="chat.id"
                  draggable="true"
                  class="group relative flex items-center ml-5 rounded-xl px-2.5 py-2 hover:bg-accented/50 cursor-pointer transition-colors select-none active:opacity-60"
                  :class="{ 'bg-accented font-medium': route.path === `/chat/${chat.id}` }"
                  @click="router.push(`/chat/${chat.id}`)"
                  @dragstart="handleDragStart(chat.id, $event)"
                >
                  <UIcon name="i-lucide-message-circle" class="w-4 h-4 text-muted shrink-0 mr-2" />
                  <span class="flex-1 truncate text-sm" :class="chat.label === 'Untitled' ? 'text-muted' : ''">
                    {{ chat.label || 'Untitled' }}
                  </span>
                  <!-- Chat actions "..." -->
                  <div class="absolute right-1.5 opacity-0 group-hover:opacity-100 transition-opacity" @click.stop>
                    <UDropdownMenu :items="getChatActions({ id: chat.id, label: chat.label, topicId: (chat as any).topicId })" :content="{ align: 'end' }">
                      <UButton
                        as="div"
                        icon="i-lucide-ellipsis"
                        color="neutral"
                        variant="ghost"
                        size="sm"
                        class="rounded-lg"
                        aria-label="Chat actions"
                      />
                    </UDropdownMenu>
                  </div>
                </div>
                <!-- Empty state for topic -->
                <p v-if="!getTopicChats(topic.id).length" class="ml-6 text-xs text-muted px-2 py-1.5 italic">
                  No chats
                </p>
              </template>
            </div>
          </template>

          <!-- Standalone Chats (no topic, Draggable & Drop target to remove from topic) -->
          <template v-if="standaloneChats.length">
            <p
              class="text-xs font-semibold text-muted uppercase tracking-wider px-2.5 pt-4 pb-1.5 rounded-xl transition-all"
              :class="{ 'ring-2 ring-zinc-400 dark:ring-zinc-600 bg-zinc-500/10 text-zinc-300': dragOverStandalone }"
              @dragover.prevent="handleDragOverStandalone($event)"
              @dragleave="handleDragLeaveStandalone()"
              @drop.prevent="handleDropOnStandalone($event)"
            >
              Chats
            </p>
            <div
              v-for="chat in standaloneChats"
              :key="chat.id"
              draggable="true"
              class="group relative flex items-center rounded-xl px-3 py-2.5 hover:bg-accented/50 cursor-pointer transition-colors select-none active:opacity-60"
              :class="{ 'bg-accented font-medium text-highlighted shadow-xs': route.path === `/chat/${chat.id}` }"
              @click="router.push(`/chat/${chat.id}`)"
              @dragstart="handleDragStart(chat.id, $event)"
            >
              <span class="flex-1 truncate text-[14.5px] sm:text-[15px] leading-relaxed" :class="chat.label === 'Untitled' ? 'text-muted' : ''">
                {{ chat.label?.replace(/^🌱\s*/, '') || 'Untitled' }}
              </span>
              <!-- Chat actions "..." -->
              <div class="absolute right-1.5 opacity-0 group-hover:opacity-100 group-has-data-[state=open]:opacity-100 transition-opacity" @click.stop>
                <UDropdownMenu :items="getChatActions({ id: chat.id, label: chat.label, topicId: (chat as any).topicId })" :content="{ align: 'end' }">
                  <UButton
                    as="div"
                    icon="i-lucide-ellipsis"
                    color="neutral"
                    variant="link"
                    size="sm"
                    class="rounded-lg hover:bg-accented/50 focus-visible:bg-accented/50 data-[state=open]:bg-accented/50 cursor-pointer p-1"
                    aria-label="Chat actions"
                    tabindex="-1"
                    @click.stop
                  />
                </UDropdownMenu>
              </div>
            </div>
          </template>

        </div>
      </template>

      <template #footer="{ collapsed }">
        <div :class="['flex items-center w-full', collapsed ? 'justify-center px-0' : 'px-1']">
          <!-- Settings Circle Button -->
          <UButton
            icon="i-lucide-settings"
            color="neutral"
            variant="ghost"
            class="w-10 h-10 rounded-full flex items-center justify-center bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-800 hover:text-zinc-900 dark:hover:text-zinc-100 transition-all cursor-pointer shadow-xs active:scale-95 shrink-0"
            aria-label="Settings"
            :ui="{ leadingIcon: 'w-5.5 h-5.5' }"
            @click="showSettingsModal = true"
          />
        </div>
      </template>
    </UDashboardSidebar>

    <UDashboardSearch
      v-model:open="searchOpen"
      placeholder="Search chats..."
      :groups="[{
        id: 'links',
        items: [{
          label: 'New chat',
          to: '/',
          icon: 'i-lucide-circle-plus'
        }, {
          label: 'Library',
          to: '/library',
          icon: 'i-lucide-library'
        }]
      }, ...searchGroups]"
    />

    <div class="flex-1 flex my-3.5 mr-3.5 ml-2.5 rounded-2xl ring-1 ring-zinc-200/80 dark:ring-zinc-800/80 bg-white dark:bg-zinc-900 shadow-sm min-w-0 overflow-hidden">
      <RouterView :key="route.path" />
    </div>

    <!-- Modal for "Add to Topic" -->
    <ModalSelectTopic
      v-if="showSelectTopicModal"
      v-model:open="showSelectTopicModal"
      :chat-id="targetChatIdForTopicModal || undefined"
      :topics="topics"
      @select-topic="handleSelectTopicForChat"
      @create-new-topic="targetChatIdForTopicModal ? createTopicForChat(targetChatIdForTopicModal) : null"
    />

    <!-- Modal for System Settings -->
    <ModalSettings
      v-if="showSettingsModal"
      v-model:open="showSettingsModal"
    />
  </UDashboardGroup>
</template>
