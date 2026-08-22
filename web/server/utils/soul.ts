import { $fetch } from 'ofetch'
import { logger } from './logger'
import { AGENT_BASE_URL, agentHeaders } from './agent-client'

/**
 * Invokes Data Persistence Layer Infrastructure Summarizer Service.
 * The summarizer extracts topic discussion content, generates Title, Description, Soul.md, and Tags,
 * and directly persists all artifacts into data-persistence/data/topics/<topicId>/
 */
export async function requestTopicSummarizerFromPersistence(
  topicId: string,
  discussionText: string,
  customTitle?: string,
  existingInfo?: Record<string, any>
): Promise<{
  title: string
  description?: string
  soulContent: string
  tags?: string[]
} | null> {
  try {
    const res: any = await $fetch(`${AGENT_BASE_URL}/api/topics/summarize`, {
      method: 'POST',
      timeout: 70000,
      headers: agentHeaders(),
      body: {
        topic_id: topicId,
        discussion_text: discussionText,
        custom_title: customTitle,
        existing_info: existingInfo
      }
    })
    if (res && res.title) {
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
