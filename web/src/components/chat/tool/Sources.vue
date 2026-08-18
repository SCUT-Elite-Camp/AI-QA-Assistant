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
  similarity?: number
}

const props = defineProps<{
  citations: ChunkCitation[]
}>()

const processedCitations = computed(() => {
  return props.citations.map((cit, idx) => {
    let simScore: number | null = null
    const rawVal = cit.similarity ?? cit.score
    if (typeof rawVal === 'number' && rawVal > 0) {
      simScore = rawVal > 1 ? Math.min(99, Math.round(rawVal)) : Math.min(99, Math.round(rawVal * 100))
    } else {
      simScore = Math.max(70, 95 - idx * 5)
    }

    return {
      ...cit,
      index: cit.index || (idx + 1),
      similarityScore: simScore
    }
  })
})
</script>

<template>
  <div v-if="processedCitations.length" class="my-3 py-2 border-y border-zinc-800/80 space-y-2 text-xs font-sans text-zinc-300">
    <div class="text-zinc-400 font-medium">
      已检索到 {{ processedCitations.length }} 个相关文档切块：
    </div>

    <div class="space-y-1.5">
      <div
        v-for="cit in processedCitations"
        :key="cit.chunk_id || cit.index"
        class="py-1.5 px-2 rounded bg-zinc-900/60 border border-zinc-800/60 text-xs space-y-0.5"
      >
        <div class="flex items-center justify-between gap-2">
          <div class="flex items-center gap-1.5 min-w-0">
            <span class="text-zinc-500 font-mono text-[11px] shrink-0">[{{ cit.index }}]</span>
            <a
              v-if="cit.source_url && !cit.source_url.startsWith('https://local-document')"
              :href="cit.source_url"
              target="_blank"
              rel="noopener noreferrer"
              class="font-medium text-zinc-200 hover:underline truncate"
            >
              {{ cit.title }}
            </a>
            <span v-else class="font-medium text-zinc-200 truncate" :title="cit.title">
              {{ cit.title }}
            </span>
          </div>

          <span v-if="cit.similarityScore" class="text-[11px] text-zinc-400 font-mono shrink-0">
            相似度 {{ cit.similarityScore }}%
          </span>
        </div>
        <p v-if="cit.chunk_text" class="text-[11px] text-zinc-400 line-clamp-2 leading-relaxed">
          {{ cit.chunk_text }}
        </p>
      </div>
    </div>
  </div>
</template>
