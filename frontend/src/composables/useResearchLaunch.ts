import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { $fetch } from 'ofetch'
import { useResearchApi } from './useResearchApi'
import { formatResearchError } from '../utils/research'
import { useChats } from './useChats'
import { useCsrf } from './useCsrf'
import { useUserSession } from './useUserSession'

export function useResearchLaunch() {
  const router = useRouter()
  const api = useResearchApi()
  const { fetchChats } = useChats()
  const { csrf, headerName } = useCsrf()
  const { user, fetchSession } = useUserSession()
  const launchingResearch = ref(false)
  const researchLaunchError = ref('')
  let pendingJob: { key: string, id: string } | null = null

  async function launchResearch(query: string, documentIds: string[] = []) {
    const normalizedQuery = query.trim()
    if (!normalizedQuery || launchingResearch.value) return false
    if (!documentIds.length) {
      researchLaunchError.value = 'Select at least one knowledge base document before starting Deep Research.'
      return false
    }

    launchingResearch.value = true
    researchLaunchError.value = ''
    try {
      if (!user.value) await fetchSession()
      if (!user.value) throw new Error('Sign in before starting Deep Research.')
      const uniqueDocumentIds = [...new Set(documentIds)].sort()
      const requestKey = JSON.stringify([normalizedQuery, uniqueDocumentIds])
      if (pendingJob?.key !== requestKey) {
        const job = await api.createJob({
          schema_version: 'research.v2',
          query: normalizedQuery,
          source_scope: {
            knowledge_base_ids: [],
            document_ids: uniqueDocumentIds,
            topic: Array.from(normalizedQuery).slice(0, 200).join(''),
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
          user_notes: 'Prefer official and primary sources, cross-check key facts, and state anything that cannot be verified.',
        })
        pendingJob = { key: requestKey, id: job.research_id }
      }
      const researchId = pendingJob.id
      await $fetch('/api/research/chats', {
        method: 'POST',
        headers: { [headerName]: csrf() },
        body: { researchId, query: normalizedQuery },
      })
      await fetchChats()
      await router.push(`/research/${researchId}`)
      pendingJob = null
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
