<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Navbar from '../../components/Navbar.vue'
import ResearchForm from '../../components/research/ResearchForm.vue'
import { useResearchApi } from '../../composables/useResearchApi'
import type { ResearchRequest } from '../../types/research'
import { formatResearchError } from '../../utils/research'

const route = useRoute()
const router = useRouter()
const api = useResearchApi()
const submitting = ref(false)
const error = ref('')

async function create(request: ResearchRequest) {
  submitting.value = true
  error.value = ''
  try {
    const job = await api.createJob(request)
    await router.push(`/research/${job.research_id}`)
  } catch (reason) {
    error.value = formatResearchError(reason)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <UDashboardPanel
    id="research-new"
    class="min-h-0 w-full"
    :ui="{ body: 'p-0 sm:p-0' }"
  >
    <template #header>
      <Navbar>
        <template #title>
          <div class="flex items-center gap-2">
            <UIcon
              name="i-lucide-telescope"
              class="text-primary"
            /><span class="font-semibold">Deep Research</span>
          </div>
        </template>
      </Navbar>
    </template>
    <template #body>
      <UContainer class="w-full max-w-4xl py-10 sm:py-14">
        <div class="mb-8">
          <UBadge
            color="primary"
            variant="soft"
            label="Local Deep Research"
          /><h1 class="mt-3 text-3xl font-bold text-highlighted">
            开始一项深度研究
          </h1><p class="mt-3 max-w-2xl text-muted">
            选择明确的本地资料范围。系统会先生成研究计划，只有在你确认后才开始执行。
          </p>
        </div>
        <div
          v-if="api.useMock"
          class="mb-5 rounded-lg border border-warning/30 bg-warning/5 p-3 text-sm text-warning"
        >
          当前使用 Research Mock 模式，适合前端独立验收。
        </div>
        <div
          v-if="error"
          class="mb-5 flex gap-2 rounded-lg border border-error/30 bg-error/5 p-3 text-sm text-error"
        >
          <UIcon
            name="i-lucide-circle-alert"
            class="mt-0.5 shrink-0"
          /><span>{{ error }}</span>
        </div>
        <UCard>
          <ResearchForm
            :initial-query="typeof route.query.q === 'string' ? route.query.q : ''"
            :submitting="submitting"
            @submit="create"
          />
        </UCard>
      </UContainer>
    </template>
  </UDashboardPanel>
</template>
