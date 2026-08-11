<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  open: boolean
  docId?: string
  docTitle?: string
  docContent?: string
  targetSnippet?: string
}>()

const emit = defineEmits<{
  (e: 'update:open', val: boolean): void
  (e: 'askSelectedText', selectedText: string, contextText: string): void
}>()

const loading = ref(false)
const doc = ref<any>(null)
const selectedText = ref('')
const selectionPopoverPos = ref<{ x: number; y: number } | null>(null)

async function fetchDoc() {
  if (props.docContent) {
    doc.value = {
      title: props.docTitle || '文档详情',
      content: props.docContent
    }
    return
  }

  if (!props.docId) {
    doc.value = {
      title: props.docTitle || '文档详情',
      content: props.targetSnippet || '暂无详细内容'
    }
    return
  }

  loading.value = true
  try {
    const res = await fetch(`/api/documents/${props.docId}`)
    if (res.ok) {
      doc.value = await res.json()
      if (props.docTitle) doc.value.title = props.docTitle
    } else {
      doc.value = {
        title: props.docTitle || '文档详情',
        content: props.targetSnippet || '暂无详细内容'
      }
    }
  } catch (e) {
    doc.value = {
      title: props.docTitle || '文档详情',
      content: props.targetSnippet || '暂无详细内容'
    }
  } finally {
    loading.value = false
  }
}

function handleTextSelection() {
  const selection = window.getSelection()
  const text = selection?.toString().trim()
  if (text && text.length > 2) {
    selectedText.value = text
    const range = selection?.getRangeAt(0)
    const rect = range?.getBoundingClientRect()
    if (rect) {
      selectionPopoverPos.value = {
        x: rect.left + rect.width / 2,
        y: rect.top - 8
      }
    }
  } else {
    selectedText.value = ''
    selectionPopoverPos.value = null
  }
}

function triggerAsk() {
  if (selectedText.value) {
    emit('askSelectedText', selectedText.value, doc.value?.content?.slice(0, 300) || '')
    selectedText.value = ''
    selectionPopoverPos.value = null
  }
}

watch(() => props.open, (val) => {
  if (val) fetchDoc()
}, { immediate: true })
</script>

<template>
  <UModal :open="open" prevent-close :ui="{ width: 'sm:max-w-4xl' }" @update:open="emit('update:open', $event)">
    <template #content>
      <div class="p-6 bg-zinc-950 text-zinc-100 rounded-3xl space-y-4 max-h-[80vh] overflow-y-auto border border-zinc-800">
        <!-- Header -->
        <div class="flex items-center justify-between pb-3 border-b border-zinc-800">
          <div class="flex items-center gap-2 font-semibold text-zinc-100 truncate pr-4">
            <UIcon name="i-heroicons-document-text" class="w-5 h-5 text-emerald-400 shrink-0" />
            <span class="truncate">{{ doc?.title || docTitle || 'Document Content' }}</span>
          </div>
          <UButton color="neutral" variant="ghost" icon="i-heroicons-x-mark" size="sm" class="rounded-full text-zinc-400 hover:text-white" @click="emit('update:open', false)" />
        </div>

        <div class="py-2 relative" @mouseup="handleTextSelection">
          <div v-if="loading" class="text-center py-12 text-zinc-400 text-xs flex items-center justify-center gap-2">
            <UIcon name="i-heroicons-arrow-path" class="w-4 h-4 animate-spin text-emerald-500" />
            <span>Loading document content...</span>
          </div>

          <div v-else-if="!doc" class="text-center py-12 text-xs text-zinc-400">
            No content available.
          </div>

          <div v-else class="space-y-4 text-sm text-zinc-200 leading-relaxed select-text">
            <div class="whitespace-pre-wrap font-mono text-xs leading-6 bg-zinc-900 p-4 rounded-xl border border-zinc-800 text-zinc-300">
              {{ doc.content || doc.snippet }}
            </div>
          </div>

          <!-- Floating Selection Ask Badge -->
          <div
            v-if="selectionPopoverPos && selectedText"
            class="fixed z-50 transform -translate-x-1/2 -translate-y-full mb-2 bg-emerald-600 text-white shadow-xl rounded-full px-3 py-1.5 text-xs font-semibold flex items-center gap-1.5 cursor-pointer hover:bg-emerald-500 transition-all scale-105"
            :style="{ left: selectionPopoverPos.x + 'px', top: selectionPopoverPos.y + 'px' }"
            @click="triggerAsk"
          >
            <UIcon name="i-heroicons-sparkles" class="w-3.5 h-3.5" />
            <span>Ask Selected Text</span>
          </div>
        </div>
      </div>
    </template>
  </UModal>
</template>
