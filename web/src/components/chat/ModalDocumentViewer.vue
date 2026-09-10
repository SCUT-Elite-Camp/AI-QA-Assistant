<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { $fetch } from 'ofetch'
import type { ChunkCitation } from './tool/Sources.vue'
import ChatComark from './Comark'

const props = defineProps<{
  open: boolean
  doc: ChunkCitation | null
  allCitations?: ChunkCitation[]
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
}>()

const loading = ref(false)
const error = ref<string | null>(null)
const fullDoc = ref<{
  doc_id: string
  title: string
  content: string
  chunks?: any[]
  address?: string
  last_updated?: string
} | null>(null)

// Find all retrieved chunks that belong to this document, deduplicated by chunk identifier
const relevantChunks = computed(() => {
  if (!props.doc) return []
  const list = props.allCitations || [props.doc]
  const seen = new Set<string>()
  const result: ChunkCitation[] = []

  for (const c of list) {
    const isSameDoc = (c.doc_id && c.doc_id === props.doc?.doc_id) || 
                      (c.title && c.title === props.doc?.title)
    const text = (c.chunk_text || (c as any).snippet || '').trim()
    if (isSameDoc && text) {
      const key = c.chunk_id || text.slice(0, 50)
      if (!seen.has(key)) {
        seen.add(key)
        result.push(c)
      }
    }
  }
  return result
})

interface ContentSegment {
  id: string
  text: string
  isHighlighted: boolean
  chunkIndex?: number
}

const contentSegments = computed<ContentSegment[]>(() => {
  const fullContent = fullDoc.value?.content || ''
  if (!fullContent) return []
  
  const chunks = relevantChunks.value
  if (!chunks || chunks.length === 0) {
    return [{ id: 'seg-norm-0', text: fullContent, isHighlighted: false }]
  }

  interface MatchItem {
    chunkIndex: number
    start: number
    end: number
    chunkText: string
  }

  const matches: MatchItem[] = []

  for (let i = 0; i < chunks.length; i++) {
    const rawChunk = (chunks[i].chunk_text || (chunks[i] as any).snippet || '').trim()
    if (!rawChunk || rawChunk.length < 5) continue

    let startIdx = fullContent.indexOf(rawChunk)
    if (startIdx === -1) {
      const normChunk = rawChunk.replace(/\r\n/g, '\n')
      const normContent = fullContent.replace(/\r\n/g, '\n')
      startIdx = normContent.indexOf(normChunk)
      if (startIdx !== -1) {
        matches.push({
          chunkIndex: i + 1,
          start: startIdx,
          end: startIdx + normChunk.length,
          chunkText: normChunk
        })
        continue
      }

      // Paragraph fallback
      const paras = rawChunk.split(/\n\s*\n/).map(p => p.trim()).filter(p => p.length > 25)
      for (const p of paras) {
        const s = fullContent.indexOf(p)
        if (s !== -1) {
          matches.push({
            chunkIndex: i + 1,
            start: s,
            end: s + p.length,
            chunkText: p
          })
          break
        }
      }
    } else {
      matches.push({
        chunkIndex: i + 1,
        start: startIdx,
        end: startIdx + rawChunk.length,
        chunkText: rawChunk
      })
    }
  }

  if (matches.length === 0) {
    return [{ id: 'seg-norm-0', text: fullContent, isHighlighted: false }]
  }

  // Sort matches by start index ascending
  matches.sort((a, b) => a.start - b.start)

  const segments: ContentSegment[] = []
  let cursor = 0

  for (let i = 0; i < matches.length; i++) {
    const m = matches[i]
    const start = Math.max(cursor, m.start)
    
    // If the next match starts before this one ends (overlap), truncate this chunk at next match start so both get their own header
    let end = m.end
    if (i + 1 < matches.length && matches[i + 1].start < end) {
      end = matches[i + 1].start
    }

    // Normal content before this chunk
    if (start > cursor) {
      const beforeText = fullContent.slice(cursor, start).trim()
      if (beforeText) {
        segments.push({
          id: `seg-norm-${cursor}`,
          text: beforeText,
          isHighlighted: false
        })
      }
    }

    // This highlighted chunk segment
    const chunkText = fullContent.slice(start, end).trim()
    if (chunkText) {
      segments.push({
        id: `chunk-block-${m.chunkIndex}`,
        text: chunkText,
        isHighlighted: true,
        chunkIndex: m.chunkIndex
      })
    }

    cursor = end
  }

  // Remaining normal content
  if (cursor < fullContent.length) {
    const afterText = fullContent.slice(cursor).trim()
    if (afterText) {
      segments.push({
        id: `seg-norm-${cursor}`,
        text: afterText,
        isHighlighted: false
      })
    }
  }

  return segments
})

function scrollToChunk(chunkIndex: number) {
  const el = document.getElementById(`chunk-block-${chunkIndex}`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
}

async function loadFullDocument() {
  if (!props.doc) return
  loading.value = true
  error.value = null
  fullDoc.value = null

  try {
    const targetId = props.doc.doc_id || props.doc.title
    const data = await $fetch<any>(`/api/documents/${encodeURIComponent(targetId)}`)
    fullDoc.value = data
  } catch (err: any) {
    console.error('[ModalDocumentViewer] fetch error:', err)
    error.value = err.data?.message || err.message || 'Failed to load document content'
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.open, props.doc],
  ([isOpen, currentDoc]) => {
    if (isOpen && currentDoc) {
      loadFullDocument()
    }
  },
  { immediate: true }
)

function getDocIcon(title?: string): string {
  const name = (title || '').toLowerCase()
  if (name.endsWith('.md') || name.endsWith('.markdown')) return 'i-lucide-file-text'
  if (name.endsWith('.pdf')) return 'i-lucide-file-type'
  if (name.endsWith('.py') || name.endsWith('.ts') || name.endsWith('.js') || name.endsWith('.vue') || name.endsWith('.json') || name.endsWith('.sql')) return 'i-lucide-file-code'
  if (name.startsWith('http://') || name.startsWith('https://')) return 'i-lucide-globe'
  return 'i-lucide-file-text'
}
</script>

<template>
  <UModal
    :open="open"
    :ui="{
      content: 'sm:max-w-5xl md:max-w-6xl w-[92vw] rounded-3xl p-0 overflow-hidden shadow-2xl border border-zinc-800 bg-zinc-950',
      width: 'sm:max-w-5xl md:max-w-6xl w-[92vw]'
    }"
    @update:open="emit('update:open', $event)"
  >
    <template #content>
      <div class="flex flex-col bg-zinc-950 text-zinc-100 rounded-3xl min-h-[560px] max-h-[85vh] w-full border border-zinc-800 shadow-2xl overflow-hidden font-sans">
        <!-- Header -->
        <div class="flex items-center justify-between px-6 py-4 border-b border-zinc-800 shrink-0 bg-zinc-900/70 backdrop-blur-md">
          <div class="flex items-center gap-3 min-w-0 pr-4">
            <div class="p-2.5 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 shrink-0">
              <UIcon :name="getDocIcon(fullDoc?.title || doc?.title)" class="w-6 h-6" />
            </div>
            <div class="min-w-0">
              <div class="flex items-center gap-2.5 flex-wrap">
                <h2 class="text-lg font-bold text-zinc-100 truncate tracking-tight">
                  {{ fullDoc?.title || doc?.title || 'Document' }}
                </h2>
                <span
                  v-if="relevantChunks.length > 0"
                  class="text-xs font-mono px-2.5 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400/90 font-medium shrink-0 flex items-center gap-1"
                >
                  <UIcon name="i-lucide-check-circle" class="w-3.5 h-3.5 text-emerald-400/80" />
                  {{ relevantChunks.length }} {{ relevantChunks.length === 1 ? 'chunk' : 'chunks' }} matched
                </span>
              </div>
              <p class="text-xs text-zinc-400 truncate mt-0.5 font-mono">
                Doc ID: {{ fullDoc?.doc_id || doc?.doc_id || 'N/A' }}
              </p>
            </div>
          </div>

          <div class="flex items-center gap-2.5 shrink-0">
            <UButton
              v-if="fullDoc?.address && !fullDoc.address.startsWith('https://local-document')"
              :to="fullDoc.address"
              target="_blank"
              size="xs"
              color="neutral"
              variant="outline"
              icon="i-lucide-external-link"
              class="text-zinc-300 hover:text-white rounded-xl px-3 py-1.5"
            >
              Open Source
            </UButton>
            <UButton
              color="neutral"
              variant="ghost"
              icon="i-lucide-x"
              size="sm"
              class="rounded-xl text-zinc-400 hover:text-white"
              @click="emit('update:open', false)"
            />
          </div>
        </div>

        <!-- Minimalist Quick Jump Bar -->
        <div
          v-if="relevantChunks.length > 0"
          class="px-6 py-2 bg-zinc-900/40 border-b border-zinc-800/60 flex items-center justify-between gap-3 flex-wrap text-xs shrink-0"
        >
          <div class="flex items-center gap-2 text-zinc-400 font-mono text-[11px]">
            <UIcon name="i-lucide-sparkles" class="w-3.5 h-3.5 text-emerald-400/80 shrink-0" />
            <span>{{ relevantChunks.length }} {{ relevantChunks.length === 1 ? 'chunk' : 'chunks' }} highlighted</span>
          </div>

          <div class="flex items-center gap-1.5 flex-wrap">
            <span class="text-zinc-500 text-[11px]">Jump to:</span>
            <button
              v-for="(c, idx) in relevantChunks"
              :key="`jump-${idx}`"
              type="button"
              class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-lg bg-zinc-800/80 hover:bg-zinc-800 hover:text-emerald-300 border border-zinc-700/50 text-zinc-300 font-mono text-[11px] font-medium transition-all cursor-pointer select-none active:scale-95"
              @click="scrollToChunk(idx + 1)"
            >
              <UIcon name="i-lucide-locate" class="w-3 h-3 text-emerald-400/70" />
              <span>Chunk #{{ idx + 1 }}</span>
            </button>
          </div>
        </div>

        <!-- Body / Content Viewer -->
        <div class="flex-1 p-6 md:p-8 overflow-y-auto min-h-[360px]">
          <!-- Loading State -->
          <div v-if="loading" class="flex flex-col items-center justify-center py-24 gap-3 text-zinc-400">
            <UIcon name="i-lucide-loader-2" class="w-9 h-9 animate-spin text-emerald-400" />
            <span class="text-sm">Loading document content...</span>
          </div>

          <!-- Error State -->
          <div v-else-if="error" class="flex flex-col items-center justify-center py-20 gap-3 text-center">
            <UIcon name="i-lucide-alert-circle" class="w-10 h-10 text-rose-400" />
            <span class="text-sm text-zinc-300">{{ error }}</span>
            <UButton size="xs" color="neutral" variant="outline" class="rounded-xl" @click="loadFullDocument">
              Retry
            </UButton>
          </div>

          <!-- Document Content Rendered in Segments -->
          <div v-else class="space-y-4 max-w-none text-zinc-200">
            <template v-for="seg in contentSegments" :key="seg.id">
              <!-- Highlighted Chunk Segment -->
              <div
                v-if="seg.isHighlighted"
                :id="seg.id"
                class="chunk-highlighted-box relative my-5 p-5 rounded-2xl bg-emerald-500/[0.035] border border-emerald-500/20 border-l-[3.5px] border-l-emerald-500/70 shadow-md shadow-emerald-950/10 scroll-mt-6"
              >
                <!-- Segment Badge Header -->
                <div class="flex items-center gap-1.5 mb-3 text-xs font-medium text-emerald-400/90 font-mono tracking-wide">
                  <UIcon name="i-lucide-bookmark" class="w-3.5 h-3.5 text-emerald-400/80" />
                  <span>Chunk #{{ seg.chunkIndex }}</span>
                </div>
                
                <!-- Inner Markdown Render with Clean White Text -->
                <div class="chunk-highlighted-body text-zinc-200">
                  <ChatComark :markdown="seg.text" />
                </div>
              </div>

              <!-- Normal Document Markdown Segment -->
              <div v-else class="document-normal-body text-zinc-200">
                <ChatComark :markdown="seg.text" />
              </div>
            </template>
          </div>
        </div>

        <!-- Footer -->
        <div class="px-6 py-3.5 border-t border-zinc-800 flex items-center justify-between text-xs text-zinc-400 bg-zinc-900/50 shrink-0">
          <span v-if="fullDoc?.last_updated">
            Updated: {{ new Date(fullDoc.last_updated).toLocaleString() }}
          </span>
          <span v-else>Knowledge Base Document</span>

          <UButton
            size="sm"
            color="neutral"
            variant="solid"
            class="rounded-xl px-5 font-medium"
            @click="emit('update:open', false)"
          >
            Close
          </UButton>
        </div>
      </div>
    </template>
  </UModal>
</template>

<style scoped>
/* Ensure clean, crisp white text across all markdown elements inside highlighted chunks */
.chunk-highlighted-body :deep(p),
.chunk-highlighted-body :deep(li),
.chunk-highlighted-body :deep(span),
.chunk-highlighted-body :deep(td),
.chunk-highlighted-body :deep(th),
.chunk-highlighted-body :deep(blockquote) {
  color: rgb(228, 228, 231) !important; /* text-zinc-200 */
}

.chunk-highlighted-body :deep(h1),
.chunk-highlighted-body :deep(h2),
.chunk-highlighted-body :deep(h3),
.chunk-highlighted-body :deep(h4),
.chunk-highlighted-body :deep(h5),
.chunk-highlighted-body :deep(h6),
.chunk-highlighted-body :deep(strong) {
  color: rgb(244, 244, 245) !important; /* text-zinc-100 */
}

.chunk-highlighted-body :deep(code) {
  background-color: rgba(39, 39, 42, 0.8) !important; /* zinc-800 */
  color: rgb(228, 228, 231) !important;
  border: 1px solid rgba(63, 63, 70, 0.5) !important;
}

.chunk-highlighted-body :deep(pre) {
  background-color: rgba(24, 24, 27, 0.9) !important; /* zinc-900 */
  border: 1px solid rgba(63, 63, 70, 0.5) !important;
}
</style>
