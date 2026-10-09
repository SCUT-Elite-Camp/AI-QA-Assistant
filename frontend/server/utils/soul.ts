import { $fetch } from 'ofetch'
import { logger } from './logger'
import { agentHeaders } from './agent-client'
import { getAgentBaseUrl } from './agentConfig'
import { assertDerivedSources, type EvidenceProvenance } from './sourceAccess'

/**
 * Invokes Data Persistence Layer Infrastructure Summarizer Service.
 * The summarizer extracts topic discussion content, generates Title, Description, Soul.md, and Tags,
 * and directly persists all artifacts into data-persistence/data/topics/<topicId>/
 */
export async function requestTopicSummarizerFromPersistence(
  topicId: string,
  discussionText: string,
  customTitle?: string,
  existingInfo?: Record<string, any>,
  access?: { userId: string, proof: EvidenceProvenance }
): Promise<{
  title: string
  description?: string
  soulContent: string
  tags?: string[]
} | null> {
  try {
    if (!access) return null
    await assertDerivedSources(access.userId, access.proof)
    const res: any = await $fetch(`${getAgentBaseUrl()}/api/topics/summarize`, {
      method: 'POST',
      timeout: 70000,
      redirect: 'error',
      headers: agentHeaders({ 'X-User-ID': access.userId, 'X-Agent-Internal-Token': process.env.AGENT_INTERNAL_TOKEN || '' }),
      body: {
        topic_id: topicId,
        discussion_text: discussionText,
        custom_title: customTitle,
        existing_info: existingInfo || {},
        source_dependencies: access.proof.dependencies,
        provenance_complete: access.proof.complete,
      }
    })
    if (res && res.title) {
      await assertDerivedSources(access.userId, access.proof)
      return {
        title: res.title,
        description: res.description,
        soulContent: res.soul_content,
        tags: res.tags || []
      }
    }
  } catch (err) {
    logger.warn('[PersistenceSummarizer] Failed to invoke data persistence summarizer service:', err)
  }
  return null
}

export async function generateTopicTitle(context: string): Promise<string> {
  const clean = (context || '').trim().replace(/^[\s\n\r]+/, '')
  return clean.length > 20 ? clean.slice(0, 20) : (clean || '话题项目')
}

export async function generateInitialSoul(title: string, context: string, docs: any[] = []): Promise<string> {
  return `# 话题认知: ${title}\n\n## 核心背景\n${context}\n`
}

export async function updateTopicSoul(currentSoul: string, feedbacks: any[]): Promise<string> {
  return currentSoul
}
