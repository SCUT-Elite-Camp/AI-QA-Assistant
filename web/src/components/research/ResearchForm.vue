<script setup lang="ts">
import { computed, reactive } from 'vue'
import type { ResearchRequest } from '../../types/research'

const props = defineProps<{ initialQuery?: string, submitting?: boolean }>()
const emit = defineEmits<{ submit: [request: ResearchRequest] }>()

const demo = {
  query: '核验上海酒店 650 元/晚能否报销，比较正式办法和财务 FAQ 的 500 元、700 元住宿限额。员工出差日期为 2026 年 9 月 10 日，已取得直属经理审批。',
  documentIds: [
    'demo-travel-policy-v1',
    'demo-travel-policy-v2',
    'demo-travel-faq-legacy',
  ],
  topic: '差旅报销政策版本核验',
  title: '上海差旅住宿报销政策核验报告',
  notes: '优先判断规则的生效日期和版本效力；明确披露旧 FAQ 与正式办法的冲突，不要推断资料中未说明的报销条件。',
}

const demoSources = [
  { id: 'demo-travel-policy-v1', title: '差旅管理办法 v1.0', meta: '旧版 · 截止 2026-07-31', fact: '上海限额 500 元/晚' },
  { id: 'demo-travel-policy-v2', title: '差旅管理办法 v2.0', meta: '现行 · 2026-08-01 生效', fact: '上海限额 700 元/晚；超过 600 元需审批' },
  { id: 'demo-travel-faq-legacy', title: '财务 FAQ', meta: '待同步 · 2026-07-15 更新', fact: '页面仍写 500 元/晚' },
]

const form = reactive({
  query: props.initialQuery ?? '',
  documentIds: '',
  topic: '',
  title: '',
  language: 'zh-CN' as 'zh-CN' | 'en-US',
  includeCitations: true,
  includeLimitations: true,
  notes: '',
})

const documentIds = computed(() => form.documentIds.split(/[\n,]/).map(item => item.trim()).filter(Boolean))
const valid = computed(() => form.query.trim().length > 0 && (documentIds.value.length > 0 || form.topic.trim().length > 0))
const isDemoLoaded = computed(() => demo.documentIds.every(id => documentIds.value.includes(id)))

function loadDemo() {
  form.query = demo.query
  form.documentIds = demo.documentIds.join('\n')
  form.topic = demo.topic
  form.title = demo.title
  form.notes = demo.notes
  form.includeCitations = true
  form.includeLimitations = true
}

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
    <div class="flex justify-end">
      <UButton
        type="button"
        icon="i-lucide-file-input"
        :label="isDemoLoaded ? '示例已载入' : '载入政策核验示例'"
        color="neutral"
        variant="soft"
        class="cursor-pointer"
        @click="loadDemo"
      />
    </div>

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
        仅使用所选本地资料。
      </p>
    </div>

    <div
      v-if="isDemoLoaded"
      class="rounded-xl border border-default bg-elevated/30 p-4"
    >
      <div class="flex items-center justify-between gap-3">
        <p class="text-sm font-semibold text-highlighted">
          已选资料
        </p>
        <UBadge
          color="neutral"
          variant="soft"
          label="3 份"
        />
      </div>
      <div class="mt-3 grid gap-3 lg:grid-cols-3">
        <div
          v-for="source in demoSources"
          :key="source.id"
          class="rounded-lg border border-default bg-default p-3"
        >
          <p class="text-sm font-semibold text-highlighted">
            {{ source.title }}
          </p>
          <p class="mt-1 text-xs text-muted">
            {{ source.meta }}
          </p>
          <p class="mt-3 text-xs leading-5 text-toned">
            {{ source.fact }}
          </p>
        </div>
      </div>
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
          只允许填写本地文档目录中存在的 ID；未列入清单的资料不会被执行阶段访问。
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
