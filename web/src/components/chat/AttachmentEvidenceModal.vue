<script setup lang="ts">
import { ref, watch } from 'vue'
import { $fetch } from 'ofetch'
import { useCsrf } from '../../composables/useCsrf'

const props = defineProps<{ open: boolean, attachment: any, canEdit?: boolean }>()
const emit = defineEmits<{ 'update:open': [value: boolean], updated: [] }>()
const { csrf, headerName } = useCsrf()
const evidence = ref<any[]>([])
const loading = ref(false)
const editing = ref<Record<string, string>>({})
const revisions = ref<Record<string, any[]>>({})
const previewFailed = ref<Record<string, boolean>>({})

function previewUrl(item: any) {
  const page = Number(item?.locator?.page || item?.locator?.slide || 0)
  return `/api/attachments/${props.attachment.id}/preview${page ? `?page=${page}` : ''}`
}

function bboxStyle(item: any) {
  const box = item?.locator?.bbox
  if (!Array.isArray(box) || box.length !== 4) return {}
  return {
    left: `${Number(box[0]) * 100}%`, top: `${Number(box[1]) * 100}%`,
    width: `${(Number(box[2]) - Number(box[0])) * 100}%`,
    height: `${(Number(box[3]) - Number(box[1])) * 100}%`,
  }
}

async function load() {
  if (!props.open || !props.attachment?.id) return
  loading.value = true
  try {
    const result = await $fetch<any>(`/api/attachments/${props.attachment.id}/evidence`)
    evidence.value = result.items || []
    editing.value = Object.fromEntries(evidence.value.map(item => [item.evidence_id, item.content]))
    previewFailed.value = {}
  } finally { loading.value = false }
}

async function save(item: any) {
  const result = await $fetch<any>(`/api/attachments/${props.attachment.id}/evidence/${item.evidence_id}`, {
    method: 'PATCH', headers: { [headerName]: csrf() },
    body: { expected_version: item.version, corrected_content: editing.value[item.evidence_id], reason: '人工校正' }
  })
  evidence.value = result.items || evidence.value
  emit('updated')
}

async function loadRevisions(item: any) {
  const result = await $fetch<any>(`/api/attachments/${props.attachment.id}/evidence/${item.evidence_id}/revisions`)
  revisions.value[item.evidence_id] = result.items || []
}

watch(() => [props.open, props.attachment?.id], load, { immediate: true })
</script>

<template>
  <UModal :open="open" @update:open="emit('update:open', $event)">
    <template #content>
      <div class="max-h-[80vh] overflow-y-auto p-5 space-y-4">
        <div class="flex justify-between"><div><h3 class="font-semibold">附件 Evidence 校正</h3><p class="text-xs text-muted">{{ attachment?.filename }} · 版本 {{ attachment?.evidenceVersion }}</p></div><UButton icon="i-lucide-x" variant="ghost" @click="emit('update:open', false)" /></div>
        <a :href="`/api/attachments/${attachment?.id}/content`" target="_blank" class="text-sm text-primary">打开原文件或预览</a>
        <div v-if="loading" class="text-sm text-muted">正在加载…</div>
        <div v-for="item in evidence" :key="item.evidence_id" class="rounded-lg border border-default p-3 space-y-2">
          <div class="text-xs text-muted">{{ item.source_type }} · v{{ item.version }} · 置信度 {{ item.confidence ?? '—' }} · {{ JSON.stringify(item.locator) }}</div>
          <div
            v-if="(item.locator?.page || item.locator?.slide || item.locator?.bbox) && !previewFailed[item.evidence_id]"
            class="relative max-h-72 overflow-auto rounded border border-default bg-elevated"
          >
            <img :src="previewUrl(item)" class="block w-full" alt="Evidence 页面或区域预览" @error="previewFailed[item.evidence_id] = true">
            <span v-if="item.locator?.bbox" class="pointer-events-none absolute border-2 border-red-500 bg-red-500/10" :style="bboxStyle(item)" />
          </div>
          <div class="rounded bg-elevated p-2 text-sm">
            <div class="mb-1 text-xs text-muted">原始识别结果（只读）</div>
            <div class="whitespace-pre-wrap break-words">{{ item.original_content }}</div>
          </div>
          <div class="text-xs text-muted">当前采用内容</div>
          <textarea v-model="editing[item.evidence_id]" class="w-full min-h-24 rounded border border-default bg-default p-2 text-sm" :readonly="!canEdit" />
          <div class="flex gap-2"><UButton v-if="canEdit" label="保存校正" size="xs" @click="save(item)" /><UButton label="修订历史" size="xs" variant="soft" @click="loadRevisions(item)" /></div>
          <div v-for="revision in revisions[item.evidence_id] || []" :key="revision.id" class="text-xs text-muted">v{{ revision.from_version }}→v{{ revision.to_version }} · {{ revision.reason }} · {{ revision.actor_id }}</div>
        </div>
      </div>
    </template>
  </UModal>
</template>
