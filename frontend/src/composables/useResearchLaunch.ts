import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { $fetch } from 'ofetch'
import { useResearchApi } from './useResearchApi'
import { formatResearchError } from '../utils/research'
import { useChats } from './useChats'
import { useCsrf } from './useCsrf'

export function useResearchLaunch() {
  const router = useRouter()
  const api = useResearchApi()
  const { fetchChats } = useChats()
  const { csrf, headerName } = useCsrf()
  const launchingResearch = ref(false)
  const researchLaunchError = ref('')

  async function launchResearch(query: string, documentIds: string[] = []) {
    const normalizedQuery = query.trim()
    if (!normalizedQuery || launchingResearch.value) return false
    if (!documentIds.length) {
      researchLaunchError.value = '请先选择至少一份本地知识库文件。'
      return false
    }

    launchingResearch.value = true
    researchLaunchError.value = ''
    try {
      const job = await api.createJob({
        schema_version: 'research.v2',
        query: normalizedQuery,
        source_scope: {
          knowledge_base_ids: [],
          document_ids: [...new Set(documentIds)],
          topic: normalizedQuery,
        },
        report_spec: {
          format: 'markdown',
          language: /[\u3400-\u9fff]/.test(normalizedQuery) ? 'zh-CN' : 'en-US',
          title: '',
          sections: [],
          include_citations: true,
          include_limitations: true,
        },
        profile: 'standard',
        user_notes: '优先使用官方和一手来源，交叉核验关键事实并说明无法确认的内容。',
      })
      await $fetch('/api/research/chats', {
        method: 'POST',
        headers: { [headerName]: csrf() },
        body: { researchId: job.research_id, query: normalizedQuery },
      })
      await fetchChats()
      await router.push(`/research/${job.research_id}`)
      return true
    } catch (reason) {
      researchLaunchError.value = formatResearchError(reason)
      return false
    } finally {
      launchingResearch.value = false
    }
  }

  return { launchResearch, launchingResearch, researchLaunchError }
}
