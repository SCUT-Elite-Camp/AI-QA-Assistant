<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import type { UIMessage } from 'ai'

import HitRateDrawer from './HitRateDrawer.vue'

const props = defineProps<{
  messages: UIMessage[]
}>()

const showHitRateDrawer = ref(false)

// Filter out assistant responses & associate with user questions
const turns = computed(() => {
  const list: { turnIndex: number; userMessage?: UIMessage; assistantMessage: UIMessage; questionText: string }[] = []
  let currentTurnUser: UIMessage | undefined = undefined
  let turnCount = 0

  for (const m of props.messages) {
    if (m.role === 'user') {
      currentTurnUser = m
    } else if (m.role === 'assistant') {
      turnCount++
      let qText = ''
      if (currentTurnUser) {
        if ((currentTurnUser as any).content) {
          qText = (currentTurnUser as any).content
        } else if (currentTurnUser.parts) {
          for (const p of currentTurnUser.parts) {
            if ((p.type === 'text' || p.type === 'reasoning') && (p as any).text) {
              qText = (p as any).text
              break
            }
          }
        }
      }
      qText = qText.trim().replace(/\s+/g, ' ') || `Question #${turnCount}`

      list.push({
        turnIndex: turnCount,
        userMessage: currentTurnUser,
        assistantMessage: m,
        questionText: qText
      })
      currentTurnUser = undefined
    }
  }
  return list
})

const activeTurnIndex = ref<number>(1)
const isCollapsed = ref(true)
const hoveredTurn = ref<{ turnIndex: number; questionText: string } | null>(null)
const hoveredTurnTop = ref(0)

// Scroll smoothly to target message ID
function scrollToMessage(messageId: string, turnIdx: number) {
  activeTurnIndex.value = turnIdx
  const el = document.getElementById(`msg-${messageId}`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    // Temporary highlight pulse ring for visual orientation (neutral gray)
    el.classList.add('ring-2', 'ring-zinc-400', 'dark:ring-zinc-500', 'rounded-2xl', 'transition-all', 'duration-300')
    setTimeout(() => {
      el.classList.remove('ring-2', 'ring-zinc-400', 'dark:ring-zinc-500', 'rounded-2xl', 'transition-all', 'duration-300')
    }, 1500)
  }
}

function scrollToTop() {
  const firstTurn = turns.value[0]
  if (firstTurn) {
    const firstId = firstTurn.userMessage?.id || firstTurn.assistantMessage.id
    const firstEl = document.getElementById(`msg-${firstId}`)
    if (firstEl) {
      firstEl.scrollIntoView({ behavior: 'smooth', block: 'start' })
      return
    }
  }
  window.scrollTo({ top: 0, behavior: 'smooth' })
  document.documentElement.scrollTo({ top: 0, behavior: 'smooth' })
}

function scrollToBottom() {
  const lastTurn = turns.value[turns.value.length - 1]
  if (lastTurn) {
    const lastId = lastTurn.assistantMessage.id
    const lastEl = document.getElementById(`msg-${lastId}`)
    if (lastEl) {
      lastEl.scrollIntoView({ behavior: 'smooth', block: 'end' })
      return
    }
  }
  window.scrollTo({ top: 99999, behavior: 'smooth' })
  document.documentElement.scrollTo({ top: 99999, behavior: 'smooth' })
}

function onTurnHover(e: MouseEvent, turn: { turnIndex: number; questionText: string }) {
  if (!isCollapsed.value) return
  hoveredTurn.value = turn
  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
  hoveredTurnTop.value = rect.top + rect.height / 2
}

function onTurnLeave() {
  hoveredTurn.value = null
}

// IntersectionObserver to auto-update active turn index on scrolling
let observer: IntersectionObserver | null = null

function setupObserver() {
  if (observer) observer.disconnect()
  if (typeof window === 'undefined' || !window.IntersectionObserver) return

  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          const id = entry.target.getAttribute('data-message-id')
          if (id) {
            const foundTurn = turns.value.find(t => t.assistantMessage.id === id || t.userMessage?.id === id)
            if (foundTurn) {
              activeTurnIndex.value = foundTurn.turnIndex
            }
          }
        }
      }
    },
    { threshold: 0.3 }
  )

  for (const t of turns.value) {
    const el = document.getElementById(`msg-${t.assistantMessage.id}`)
    if (el) observer.observe(el)
  }
}

watch(() => props.messages.length, () => {
  setTimeout(setupObserver, 200)
}, { immediate: true })

onMounted(() => {
  setTimeout(setupObserver, 300)
})

onUnmounted(() => {
  if (observer) observer.disconnect()
})
</script>

<template>
  <div>
    <div
      v-if="turns.length >= 1"
      class="fixed right-3.5 top-1/2 -translate-y-1/2 z-30 flex items-center justify-end pointer-events-auto select-none font-sans"
    >
      <!-- Modern Floating Glass Capsule -->
      <div
        :class="[
          'flex flex-col rounded-2xl bg-white/80 dark:bg-zinc-900/85 backdrop-blur-xl border border-zinc-200/80 dark:border-zinc-800 shadow-xl shadow-black/5 dark:shadow-black/30 transition-all duration-300 ease-out',
          isCollapsed ? 'w-10 p-1.5 items-center' : 'w-64 p-3 max-w-[85vw]'
        ]"
      >
        <!-- Top Bar: Toggle & Title -->
        <div class="flex items-center justify-between w-full pb-1.5 mb-1 border-b border-zinc-100 dark:border-zinc-800/80">
          <div v-if="!isCollapsed" class="flex items-center gap-2 text-xs font-semibold text-zinc-800 dark:text-zinc-200 px-1">
            <UIcon name="i-heroicons-bars-3-bottom-left" class="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
            <span>Outline</span>
            <span class="text-[10px] font-normal px-1.5 py-0.5 rounded-full bg-zinc-100 dark:bg-zinc-800 text-zinc-500 dark:text-zinc-400 font-mono">
              {{ turns.length }}
            </span>
          </div>

          <button
            type="button"
            :title="isCollapsed ? 'Expand outline' : 'Collapse outline'"
            class="p-1 rounded-lg text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800/80 transition-colors cursor-pointer flex items-center justify-center mx-auto sm:mx-0"
            @click="isCollapsed = !isCollapsed"
          >
            <UIcon :name="isCollapsed ? 'i-heroicons-chevron-left' : 'i-heroicons-chevron-right'" class="w-4 h-4" />
          </button>
        </div>

        <!-- Collapsed Compact View -->
        <div v-if="isCollapsed" class="flex flex-col items-center gap-1.5 py-0.5">
          <!-- Scroll to top -->
          <button
            type="button"
            title="Scroll to top"
            class="w-7 h-7 rounded-xl text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 flex items-center justify-center transition-all cursor-pointer"
            @click="scrollToTop"
          >
            <UIcon name="i-heroicons-arrow-up" class="w-3.5 h-3.5" />
          </button>

          <!-- Turn Numbers List -->
          <div class="flex flex-col gap-1.5 max-h-[45vh] overflow-y-auto no-scrollbar py-0.5">
            <button
              v-for="turn in turns"
              :key="turn.assistantMessage.id"
              type="button"
              :class="[
                'w-7 h-7 rounded-xl text-xs font-mono transition-all duration-200 flex items-center justify-center cursor-pointer border',
                activeTurnIndex === turn.turnIndex
                  ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950 font-bold border-transparent shadow-xs scale-105'
                  : 'bg-transparent text-zinc-400 dark:text-zinc-500 border-transparent hover:bg-zinc-100 dark:hover:bg-zinc-800 hover:text-zinc-800 dark:hover:text-zinc-200'
              ]"
              @click="scrollToMessage(turn.assistantMessage.id, turn.turnIndex)"
              @mouseenter="onTurnHover($event, turn)"
              @mouseleave="onTurnLeave"
            >
              {{ turn.turnIndex }}
            </button>
          </div>

          <!-- Scroll to bottom -->
          <button
            type="button"
            title="Scroll to bottom"
            class="w-7 h-7 rounded-xl text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 flex items-center justify-center transition-all cursor-pointer"
            @click="scrollToBottom"
          >
            <UIcon name="i-heroicons-arrow-down" class="w-3.5 h-3.5" />
          </button>
        </div>

        <!-- Expanded TOC View -->
        <div v-else class="flex flex-col gap-1 max-h-[55vh] overflow-y-auto no-scrollbar pr-0.5">
          <button
            v-for="turn in turns"
            :key="turn.assistantMessage.id"
            type="button"
            :class="[
              'group text-left px-2.5 py-2 rounded-xl text-xs flex items-center gap-2.5 transition-all cursor-pointer border',
              activeTurnIndex === turn.turnIndex
                ? 'bg-zinc-100 dark:bg-zinc-800/90 text-zinc-900 dark:text-white font-medium border-zinc-200 dark:border-zinc-700/80 shadow-xs'
                : 'bg-transparent border-transparent text-zinc-500 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 hover:text-zinc-900 dark:hover:text-zinc-200'
            ]"
            @click="scrollToMessage(turn.assistantMessage.id, turn.turnIndex)"
          >
            <span
              :class="[
                'w-5 h-5 rounded-lg shrink-0 font-mono text-[10px] flex items-center justify-center font-semibold transition-colors',
                activeTurnIndex === turn.turnIndex
                  ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950'
                  : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-500 dark:text-zinc-400 group-hover:bg-zinc-200 dark:group-hover:bg-zinc-700'
              ]"
            >
              {{ turn.turnIndex }}
            </span>
            <span class="truncate min-w-0 flex-1" :title="turn.questionText">
              {{ turn.questionText }}
            </span>
          </button>
        </div>

        <!-- Expanded Footer Actions -->
        <div v-if="!isCollapsed" class="flex items-center justify-between pt-2 mt-1.5 border-t border-zinc-100 dark:border-zinc-800/80 px-1 text-xs text-zinc-400">
          <button
            type="button"
            class="hover:text-zinc-800 dark:hover:text-zinc-200 flex items-center gap-1 cursor-pointer transition-colors"
            @click="scrollToTop"
          >
            <UIcon name="i-heroicons-arrow-up" class="w-3.5 h-3.5" />
            <span>Top</span>
          </button>
          <button
            type="button"
            class="hover:text-zinc-800 dark:hover:text-zinc-200 flex items-center gap-1 cursor-pointer transition-colors"
            @click="scrollToBottom"
          >
            <UIcon name="i-heroicons-arrow-down" class="w-3.5 h-3.5" />
            <span>Latest</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Floating Hover Tooltip for Collapsed Mode -->
    <Teleport to="body">
      <Transition name="fade-scale">
        <div
          v-if="isCollapsed && hoveredTurn"
          class="fixed right-16 z-50 max-w-xs px-3 py-2 text-xs rounded-xl bg-zinc-900/95 dark:bg-zinc-800/95 text-zinc-100 shadow-xl border border-zinc-700/50 backdrop-blur-md pointer-events-none -translate-y-1/2 font-sans"
          :style="{ top: `${hoveredTurnTop}px` }"
        >
          <div class="flex items-center gap-1.5 text-zinc-400 text-[10px] mb-0.5 font-mono">
            <span>Question #{{ hoveredTurn.turnIndex }}</span>
          </div>
          <div class="line-clamp-2 text-zinc-200 leading-snug">
            {{ hoveredTurn.questionText }}
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Hit Rate Side Drawer Component -->
    <HitRateDrawer
      :open="showHitRateDrawer"
      :messages="props.messages"
      @update:open="showHitRateDrawer = $event"
    />
  </div>
</template>

<style scoped>
.no-scrollbar::-webkit-scrollbar {
  display: none;
}
.no-scrollbar {
  -ms-overflow-style: none;
  scrollbar-width: none;
}

.fade-scale-enter-active,
.fade-scale-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.fade-scale-enter-from,
.fade-scale-leave-to {
  opacity: 0;
  transform: translateY(-50%) translateX(6px) scale(0.96);
}
</style>
