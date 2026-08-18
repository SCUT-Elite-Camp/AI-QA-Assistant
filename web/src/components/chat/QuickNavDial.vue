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
        if (currentTurnUser.content) {
          qText = currentTurnUser.content
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

// Scroll smoothly to target message ID
function scrollToMessage(messageId: string, turnIdx: number) {
  activeTurnIndex.value = turnIdx
  const el = document.getElementById(`msg-${messageId}`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    // Temporary highlight pulse ring for visual orientation
    el.classList.add('ring-2', 'ring-emerald-400', 'rounded-2xl', 'transition-all', 'duration-300')
    setTimeout(() => {
      el.classList.remove('ring-2', 'ring-emerald-400', 'rounded-2xl', 'transition-all', 'duration-300')
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
      class="absolute right-0 top-1/2 -translate-y-1/2 z-30 flex items-center justify-end pointer-events-auto select-none"
    >
      <!-- Semi-circular Right Dock Container -->
      <div
        :class="[
          'flex flex-col py-3 px-2 rounded-l-2xl bg-zinc-950/90 dark:bg-zinc-900/95 backdrop-blur-md border-l border-t border-b border-zinc-700/70 shadow-2xl transition-all duration-300',
          isCollapsed ? 'w-11 items-center' : 'w-56 sm:w-64 max-w-[85vw]'
        ]"
      >
        <!-- Header: Quick Nav Title & Controls -->
        <div class="flex items-center justify-between pb-2 mb-1 border-b border-zinc-800/80 px-1">
          <div v-if="!isCollapsed" class="flex items-center gap-1.5 text-xs font-semibold text-zinc-200">
            <UIcon name="i-heroicons-list-bullet" class="w-4 h-4 text-emerald-400" />
            <span>Nav ({{ turns.length }})</span>
          </div>
          <button
            type="button"
            :title="isCollapsed ? 'Expand navigation' : 'Collapse navigation'"
            class="p-1 rounded-lg text-zinc-400 hover:text-white hover:bg-zinc-800 transition-colors mx-auto sm:mx-0 cursor-pointer"
            @click="isCollapsed = !isCollapsed"
          >
            <UIcon :name="isCollapsed ? 'i-heroicons-chevron-left' : 'i-heroicons-chevron-right'" class="w-4 h-4" />
          </button>
        </div>

        <!-- Top / Bottom Scroll Action Buttons (Compact View) -->
        <div v-if="isCollapsed" class="flex flex-col items-center gap-1.5 my-1">
          <button
            type="button"
            title="Scroll to Top"
            class="w-7 h-7 rounded-full bg-zinc-800 text-zinc-400 hover:text-emerald-400 hover:bg-zinc-700 flex items-center justify-center transition-all cursor-pointer"
            @click="scrollToTop"
          >
            <UIcon name="i-heroicons-arrow-up" class="w-3.5 h-3.5" />
          </button>

          <div class="flex flex-col gap-1 max-h-[45vh] overflow-y-auto no-scrollbar">
            <button
              v-for="turn in turns"
              :key="turn.assistantMessage.id"
              type="button"
              :title="turn.questionText"
              :class="[
                'w-7 h-7 rounded-full text-[11px] font-mono font-medium flex items-center justify-center transition-all cursor-pointer border',
                activeTurnIndex === turn.turnIndex
                  ? 'bg-emerald-500 text-white border-emerald-400 font-bold scale-105 shadow-sm shadow-emerald-500/20'
                  : 'bg-zinc-800 text-zinc-400 border-zinc-700 hover:bg-zinc-700 hover:text-zinc-200'
              ]"
              @click="scrollToMessage(turn.assistantMessage.id, turn.turnIndex)"
            >
              #{{ turn.turnIndex }}
            </button>
          </div>

          <button
            type="button"
            title="Scroll to Bottom"
            class="w-7 h-7 rounded-full bg-zinc-800 text-zinc-400 hover:text-emerald-400 hover:bg-zinc-700 flex items-center justify-center transition-all cursor-pointer"
            @click="scrollToBottom"
          >
            <UIcon name="i-heroicons-arrow-down" class="w-3.5 h-3.5" />
          </button>
        </div>

        <!-- Expanded View: List of User Questions with Jump Action -->
        <div v-else class="flex flex-col gap-1.5 max-h-[60vh] overflow-y-auto no-scrollbar pr-0.5">
          <button
            v-for="turn in turns"
            :key="turn.assistantMessage.id"
            type="button"
            :class="[
              'group text-left px-2.5 py-2 rounded-xl text-xs flex items-center gap-2 border transition-all cursor-pointer truncate',
              activeTurnIndex === turn.turnIndex
                ? 'bg-emerald-500/15 border-emerald-500/50 text-emerald-300 font-medium shadow-xs'
                : 'bg-zinc-900/60 border-zinc-800/80 text-zinc-300 hover:bg-zinc-800/80 hover:border-zinc-700 hover:text-white'
            ]"
            @click="scrollToMessage(turn.assistantMessage.id, turn.turnIndex)"
          >
            <span
              :class="[
                'w-5 h-5 rounded-full shrink-0 font-mono text-[10px] flex items-center justify-center font-bold',
                activeTurnIndex === turn.turnIndex ? 'bg-emerald-500 text-white' : 'bg-zinc-800 text-zinc-400 group-hover:bg-zinc-700 group-hover:text-zinc-200'
              ]"
            >
              {{ turn.turnIndex }}
            </span>
            <span class="truncate min-w-0 flex-1" :title="turn.questionText">
              {{ turn.questionText }}
            </span>
          </button>
        </div>

        <!-- Bottom Actions Bar (Expanded View) -->
        <div v-if="!isCollapsed" class="flex items-center justify-between pt-2 mt-1 border-t border-zinc-800/80 px-1 text-[11px] text-zinc-400">
          <button
            type="button"
            class="hover:text-emerald-400 flex items-center gap-1 cursor-pointer transition-colors"
            @click="scrollToTop"
          >
            <UIcon name="i-heroicons-arrow-up" class="w-3.5 h-3.5" />
            <span>Top</span>
          </button>
          <button
            type="button"
            class="hover:text-emerald-400 flex items-center gap-1 cursor-pointer transition-colors"
            @click="scrollToBottom"
          >
            <UIcon name="i-heroicons-arrow-down" class="w-3.5 h-3.5" />
            <span>Latest</span>
          </button>
        </div>
      </div>
    </div>

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
</style>
