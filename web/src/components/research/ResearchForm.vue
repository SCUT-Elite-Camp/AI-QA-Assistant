<script setup lang="ts">
import { computed, reactive } from 'vue'
import type { ResearchRequest } from '../../types/research'

const props = defineProps<{ initialQuery?: string, submitting?: boolean }>()
const emit = defineEmits<{ submit: [request: ResearchRequest] }>()

const form = reactive({
  query: props.initialQuery ?? '',
  documentIds: 'project-alpha\nproject-beta',
  topic: '',
  title: '',
  language: 'zh-CN' as 'zh-CN' | 'en-US',
  includeCitations: true,
  includeLimitations: true,
  notes: '',
})

const documentIds = computed(() => form.documentIds.split(/[\n,]/).map(item => item.trim()).filter(Boolean))
const valid = computed(() => form.query.trim().length > 0 && (documentIds.value.length > 0 || form.topic.trim().length > 0))

function submit() {
  if (!valid.value || props.submitting) return
  emit('submit', {
    schema_version: 'research.v2',
    query: form.query.trim(),
    source_scope: { knowledge_base_ids: [], document_ids: documentIds.value, topic: form.topic.trim() },
    report_spec: {
      format: 'markdown', language: form.language, title: form.title.trim(), sections: [],
      include_citations: form.includeCitations, include_limitations: form.includeLimitations,
    },
    profile: 'standard', user_notes: form.notes.trim() || null,
  })
}
</script>

<template>
  <form
    class="space-y-6"
    @submit.prevent="submit"
  >
    <div>
      <label
        for="research-query"
        class="mb-2 block text-sm font-semibold text-highlighted"
      >研究问题</label>
      <UTextarea
        id="research-query"
        v-model="form.query"
        :rows="5"
        autoresize
        class="w-full"
        placeholder="描述你希望研究的问题、比较对象和期望结论。"
      />
      <p class="mt-2 text-xs text-muted">
        Deep Research 只使用你明确选择的本地资料，不会自动访问互联网。
      </p>
    </div>

    <div class="grid gap-5 md:grid-cols-2">
      <div>
        <label
          for="research-documents"
          class="mb-2 block text-sm font-semibold text-highlighted"
        >文档 ID</label>
        <UTextarea
          id="research-documents"
          v-model="form.documentIds"
          :rows="4"
          class="w-full"
          placeholder="每行一个文档 ID"
        />
        <p class="mt-2 text-xs text-muted">
          当前演示资料：project-alpha、project-beta。
        </p>
      </div>
      <div>
        <label
          for="research-topic"
          class="mb-2 block text-sm font-semibold text-highlighted"
        >资料主题（可选）</label>
        <UInput
          id="research-topic"
          v-model="form.topic"
          class="w-full"
          placeholder="例如：部署验收资料"
        />
        <label
          for="research-title"
          class="mb-2 mt-5 block text-sm font-semibold text-highlighted"
        >报告标题（可选）</label>
        <UInput
          id="research-title"
          v-model="form.title"
          class="w-full"
          placeholder="未填写时由系统生成"
        />
      </div>
    </div>

    <div class="rounded-xl border border-default bg-elevated/40 p-4">
      <p class="mb-3 text-sm font-semibold text-highlighted">
        报告设置
      </p>
      <div class="grid gap-4 sm:grid-cols-3">
        <label class="flex items-center gap-2 text-sm"><input
          v-model="form.includeCitations"
          type="checkbox"
          class="accent-primary-500"
        >包含引用</label>
        <label class="flex items-center gap-2 text-sm"><input
          v-model="form.includeLimitations"
          type="checkbox"
          class="accent-primary-500"
        >披露资料限制</label>
        <label class="flex items-center gap-2 text-sm">语言
          <select
            v-model="form.language"
            class="rounded-md border border-default bg-default px-2 py-1 text-sm"
          >
            <option value="zh-CN">简体中文</option><option value="en-US">English</option>
          </select>
        </label>
      </div>
    </div>

    <div>
      <label
        for="research-notes"
        class="mb-2 block text-sm font-semibold text-highlighted"
      >补充说明（可选）</label>
      <UTextarea
        id="research-notes"
        v-model="form.notes"
        :rows="2"
        class="w-full"
        placeholder="例如：重点关注风险与无法确认的信息。"
      />
    </div>

    <div class="flex items-center justify-end gap-3">
      <UButton
        to="/"
        color="neutral"
        variant="ghost"
        label="返回"
      />
      <UButton
        type="submit"
        icon="i-lucide-telescope"
        label="创建研究任务"
        :loading="submitting"
        :disabled="!valid || submitting"
      />
    </div>
  </form>
</template>

