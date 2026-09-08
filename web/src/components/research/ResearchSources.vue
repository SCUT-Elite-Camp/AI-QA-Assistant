<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { ResearchCitation } from '../../types/research'

const props = defineProps<{
  citations: ResearchCitation[]
  selectedCitation?: number | null
}>()

const emit = defineEmits<{
  select: [citationNumber: number]
}>()

const openCitationNumber = ref<number | null>(props.selectedCitation ?? null)

const documents = computed(() => {
  const grouped = new Map<string, { docId: string, title: string, citations: ResearchCitation[] }>()
  for (const citation of props.citations) {
    const existing = grouped.get(citation.doc_id)
    if (existing) existing.citations.push(citation)
    else grouped.set(citation.doc_id, {
      docId: citation.doc_id,
      title: citation.title,
      citations: [citation],
    })
  }
  return [...grouped.values()]
})

watch(() => props.selectedCitation, (number) => {
  if (number != null) openCitationNumber.value = number
})

function toggleCitation(number: number) {
  openCitationNumber.value = openCitationNumber.value === number ? null : number
  if (openCitationNumber.value != null) emit('select', openCitationNumber.value)
}

function formatDate(value: string | null) {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}
</script>

<template>
  <div
    v-if="documents.length"
    class="overflow-hidden rounded-lg border border-default"
  >
    <div
      v-for="document in documents"
      :key="document.docId"
      class="border-t border-default first:border-t-0"
    >
      <div class="flex min-w-0 items-center gap-2 px-3 py-2">
        <UIcon
          name="i-lucide-file-text"
          class="size-4 shrink-0 text-dimmed"
        />
        <button
          type="button"
          class="min-w-0 flex-1 truncate text-start text-sm text-muted outline-none transition-colors hover:text-highlighted focus-visible:rounded focus-visible:ring-2 focus-visible:ring-primary"
          :aria-label="`查看 ${document.title} 的原文`"
          @click="toggleCitation(document.citations[0]!.number)"
        >
          {{ document.title }}
        </button>
        <div class="flex shrink-0 items-center gap-1">
          <button
            v-for="citation in document.citations"
            :key="citation.number"
            type="button"
            class="inline-flex size-5 items-center justify-center rounded-full text-[11px] font-semibold outline-none transition-colors focus-visible:ring-2 focus-visible:ring-primary"
            :class="openCitationNumber === citation.number ? 'bg-primary text-inverted' : 'bg-primary/10 text-primary hover:bg-primary/20'"
            :aria-label="`查看引用 ${citation.number} 原文`"
            :aria-expanded="openCitationNumber === citation.number"
            @click="toggleCitation(citation.number)"
          >
            {{ citation.number }}
          </button>
        </div>
        <UIcon
          name="i-lucide-chevron-down"
          class="size-4 shrink-0 text-dimmed transition-transform"
          :class="document.citations.some(item => item.number === openCitationNumber) ? 'rotate-180' : ''"
        />
      </div>

      <template
        v-for="citation in document.citations"
        :key="`excerpt-${citation.number}`"
      >
        <div
          v-if="openCitationNumber === citation.number"
          class="border-t border-default bg-elevated/40 px-4 py-3"
        >
          <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
            <span class="font-medium text-highlighted">[{{ citation.number }}] 原文片段</span>
            <span v-if="citation.locator">{{ citation.locator }}</span>
            <span v-if="citation.document_version">版本 {{ citation.document_version }}</span>
            <span v-if="formatDate(citation.updated_at || citation.effective_at)">
              {{ formatDate(citation.updated_at || citation.effective_at) }}
            </span>
          </div>
          <div class="evidence-scroll mt-3 max-h-72 overflow-y-auto whitespace-pre-wrap break-words pe-3 text-sm leading-6 text-highlighted selection:bg-primary/20">
            {{ citation.excerpt || '当前证据没有可显示的原文片段。' }}
          </div>
          <a
            v-if="citation.source_url && !citation.source_url.startsWith('https://local-document')"
            :href="citation.source_url"
            target="_blank"
            rel="noopener noreferrer"
            class="mt-3 inline-flex items-center gap-1 text-xs text-primary hover:underline"
          >
            打开来源
            <UIcon
              name="i-lucide-external-link"
              class="size-3"
            />
          </a>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.evidence-scroll {
  scrollbar-width: thin;
  scrollbar-color: color-mix(in srgb, currentColor 20%, transparent) transparent;
}

.evidence-scroll::-webkit-scrollbar {
  width: 5px;
}

.evidence-scroll::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: color-mix(in srgb, currentColor 20%, transparent);
}
</style>
