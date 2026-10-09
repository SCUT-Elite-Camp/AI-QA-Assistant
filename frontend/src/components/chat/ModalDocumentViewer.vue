<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { $fetch } from 'ofetch'
import type { ChunkCitation } from './tool/Sources.vue'
import ChatComark from './Comark'
import { evidenceUrl, evidenceError } from '../../utils/evidence'

const props = defineProps<{ open: boolean, doc: ChunkCitation | null, allCitations?: ChunkCitation[], messageId?: string }>()
const emit = defineEmits<{ 'update:open': [value: boolean] }>()
const loading = ref(false)
const error = ref<string | null>(null)
const evidence = ref<ChunkCitation | null>(null)
const source = ref<{ doc_id?: string, title?: string, content?: string, source_url?: string } | null>(null)
const locatedExcerpt = ref<HTMLElement | null>(null)
let requestRevision = 0
const excerpt = computed(() => evidence.value?.excerpt || evidence.value?.chunk_text || evidence.value?.snippet || '')
const version = computed(() => evidence.value?.source_version ?? evidence.value?.version)
const sourceUrl = computed(() => {
  const url = source.value?.source_url || evidence.value?.source_url || ''
  return /^https:\/\//.test(url) ? url : ''
})
const locator = computed(() => evidence.value?.locator ? JSON.stringify(evidence.value.locator) : '')
const exactLocation = computed(() => !!excerpt.value && !!source.value?.content && source.value.content.includes(excerpt.value))
const sourceSegments = computed(() => {
  const text = source.value?.content || ''
  const index = exactLocation.value ? text.indexOf(excerpt.value) : -1
  return index < 0 ? null : { before: text.slice(0, index), excerpt: excerpt.value, after: text.slice(index + excerpt.value.length) }
})
async function jumpToExcerpt() {
  await nextTick()
  locatedExcerpt.value?.scrollIntoView?.({ block: 'center', behavior: 'instant' })
  locatedExcerpt.value?.focus({ preventScroll: true })
}

async function loadFullDocument() {
  const revision = ++requestRevision
  loading.value = true
  error.value = null
  evidence.value = null
  source.value = null
  try {
    if (!props.doc) throw new Error('未选择引用。')
    if (props.messageId) {
      const result = await $fetch<{ evidence: ChunkCitation, source?: typeof source.value }>(evidenceUrl(props.messageId, props.doc.evidence_ref || ''))
      if (revision !== requestRevision) return
      evidence.value = result.evidence
      source.value = result.source ?? null
    } else {
      if (!props.doc.doc_id) throw new Error('缺少真实文档 ID，不能按标题读取原文。')
      const result = await $fetch<NonNullable<typeof source.value>>(`/api/documents/${encodeURIComponent(props.doc.doc_id)}`)
      if (revision !== requestRevision) return
      source.value = result
    }
  } catch (failure) {
    if (revision === requestRevision) error.value = evidenceError(failure)
  } finally {
    if (revision === requestRevision) loading.value = false
  }
}
watch(() => [props.open, props.doc, props.messageId], () => {
  if (props.open && props.doc) void loadFullDocument()
  else { requestRevision++; evidence.value = null; source.value = null; error.value = null; loading.value = false }
}, { immediate: true })
</script>

<template>
  <UModal :open="open" title="核对回答依据" description="查看本条回答绑定的授权原文与版本" :ui="{ content: 'sm:max-w-5xl w-[92vw]' }" @update:open="emit('update:open', $event)">
    <template #content>
      <div class="flex max-h-[85vh] flex-col rounded-xl border border-default bg-default text-default">
        <header class="flex items-center justify-between gap-4 border-b border-default px-5 py-4">
          <h2 class="min-w-0 break-words font-semibold">{{ evidence?.title || source?.title || '核对回答依据' }}</h2>
          <UButton color="neutral" variant="ghost" icon="i-lucide-x" aria-label="关闭原文窗口" @click="emit('update:open', false)" />
        </header>
        <div class="min-h-48 overflow-y-auto px-5 py-4" :aria-busy="loading">
          <p v-if="loading" role="status" aria-live="polite">正在校验当前权限并读取原文…</p>
          <div v-else-if="error" role="alert" class="space-y-3">
            <p>{{ error }}</p>
            <UButton color="neutral" variant="outline" @click="loadFullDocument">重新校验</UButton>
          </div>
          <div v-else class="space-y-4">
            <dl v-if="evidence" class="grid gap-2 text-sm">
              <div><dt class="inline text-muted">回答采用版本：</dt><dd class="inline">{{ version ?? '未知（未提供源版本）' }}</dd></div>
              <div><dt class="inline text-muted">定位：</dt><dd class="inline break-all">{{ locator || '未知；仅展示实际摘录，不声称精确定位' }}</dd></div>
              <div><dt class="inline text-muted">正文 hash：</dt><dd class="inline break-all font-mono">{{ evidence.normalized_content_hash || evidence.content_hash || '未知' }}</dd></div>
            </dl>
            <section v-if="excerpt" class="rounded-lg border border-default bg-elevated/40 p-4">
              <h3 class="mb-2 text-sm font-semibold">本次回答采用的原文片段</h3>
              <ChatComark :markdown="excerpt" />
            </section>
            <p v-if="evidence && !excerpt" role="status">授权证据未提供摘录，请重新提问获取可核对的依据。</p>
            <section v-if="source?.content" class="space-y-2">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <h3 class="text-sm font-semibold">授权原文</h3>
                <UButton v-if="exactLocation" color="neutral" variant="outline" size="sm" @click="jumpToExcerpt">跳转到原文片段</UButton>
              </div>
              <p v-if="evidence && !exactLocation" role="status" class="text-sm text-muted">无法在返回全文中精确定位该摘录；下面是授权正文，不标记为已定位。</p>
              <div v-if="sourceSegments" class="whitespace-pre-wrap break-words font-mono text-sm">
                <span>{{ sourceSegments.before }}</span><mark ref="locatedExcerpt" tabindex="-1" class="rounded bg-primary/20 text-default outline-offset-4 focus-visible:outline-2 focus-visible:outline-primary">{{ sourceSegments.excerpt }}</mark><span>{{ sourceSegments.after }}</span>
              </div>
              <ChatComark v-else :markdown="source.content" />
            </section>
            <p v-else-if="excerpt" class="text-sm text-muted">当前只展示本条回答绑定的片段，不代表已读取完整文档。未核对源站最新版。</p>
            <a v-if="sourceUrl" :href="sourceUrl" target="_blank" rel="noopener noreferrer" class="inline-block rounded text-primary underline focus-visible:outline-2 focus-visible:outline-primary">打开源站当前页面（可能不同于回答版本）</a>
          </div>
        </div>
        <footer class="flex justify-end border-t border-default px-5 py-3">
          <UButton color="neutral" @click="emit('update:open', false)">关闭</UButton>
        </footer>
      </div>
    </template>
  </UModal>
</template>
