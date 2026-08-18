<script setup lang="ts">
import { computed } from 'vue'

export interface ChunkCitation {
  index: number
  doc_id: string
  chunk_id: string
  title: string
  source_url?: string
  chunk_text?: string
  score?: number
}

const props = defineProps<{
  citations: ChunkCitation[]
}>()

/**
 * Deduplicate by doc_id: keep the first citation per document,
 * collect chunk indices for that document.
 */
const dedupedDocs = computed(() => {
  const seen = new Map<string, { citation: ChunkCitation; indices: number[] }>()
  for (const cit of props.citations) {
    if (!seen.has(cit.doc_id)) {
      seen.set(cit.doc_id, { citation: cit, indices: [cit.index] })
    } else {
      seen.get(cit.doc_id)!.indices.push(cit.index)
    }
  }
  return [...seen.values()]
})
</script>

<template>
  <div
    v-if="dedupedDocs.length"
    class="p-1 border border-default rounded-md max-h-40 overflow-y-auto"
  >
    <div
      v-for="{ citation, indices } in dedupedDocs"
      :key="citation.doc_id"
      class="flex items-center gap-2 px-2 py-1.5 text-sm rounded-md hover:bg-elevated/50 transition-colors min-w-0"
    >
      <!-- Document icon -->
      <span class="shrink-0 size-4 flex items-center justify-center opacity-60">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="size-4">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
          <polyline points="10 9 9 9 8 9" />
        </svg>
      </span>

      <!-- Title (link if url available) -->
      <a
        v-if="citation.source_url && !citation.source_url.startsWith('https://local-document')"
        :href="citation.source_url"
        target="_blank"
        rel="noopener noreferrer"
        class="truncate text-muted hover:text-default flex-1 min-w-0"
      >{{ citation.title }}</a>
      <span v-else class="truncate text-muted flex-1 min-w-0">{{ citation.title }}</span>

      <!-- Chunk index badges -->
      <span class="flex gap-1 shrink-0 ms-auto">
        <span
          v-for="idx in indices"
          :key="idx"
          class="inline-flex items-center justify-center size-4 text-[10px] font-semibold rounded-full"
          style="background: color-mix(in srgb, var(--ui-color-primary-500, #6366f1) 15%, transparent); color: var(--ui-color-primary-400, #818cf8);"
        >{{ idx }}</span>
      </span>

      <!-- local-document badge -->
      <span class="text-xs text-dimmed shrink-0 hidden sm:block">local-document</span>
    </div>
  </div>
</template>
