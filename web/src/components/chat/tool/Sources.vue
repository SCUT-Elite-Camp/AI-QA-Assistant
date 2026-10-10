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
  source_type?: 'knowledge' | 'attachment' | 'personal'
  attachment_id?: string
  evidence_id?: string
  locator?: { page?: number, slide?: number, sheet?: string, cell_range?: string, bbox?: number[] }
  version?: number
}

const props = defineProps<{
  citations: ChunkCitation[]
}>()

const emit = defineEmits<{
  'select-doc': [citation: ChunkCitation]
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
  <div v-if="dedupedDocs.length" class="source-row">
    <button
      v-for="{ citation, indices } in dedupedDocs"
      :key="citation.doc_id"
      type="button"
      class="source-chip"
      :title="citation.title"
      @click="emit('select-doc', citation)"
    >
      <span class="source-index">{{ indices[0] }}</span>
      <span class="truncate">{{ citation.title }}</span>
    </button>
  </div>
</template>
