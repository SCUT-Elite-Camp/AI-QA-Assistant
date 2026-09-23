import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams } from 'nitro/h3'
import { useDrizzle, tables, eq } from '../../../../utils/drizzle'
import { requestTopicSummarizerFromPersistence } from '../../../../utils/soul'
import { syncTopicToDisk, loadTopicFromDisk } from '../../../../utils/topicStorage'
import { requireCsrf, requireTopicRole } from '../../../../utils/attachmentAuth'

export default defineHandler(async (event) => {
  const { id } = await getValidatedRouterParams(event, z.object({
    id: z.string()
  }).parse)
  requireCsrf(event)
  await requireTopicRole(event, id, 'editor')

  const db = useDrizzle()

  const topic = await db.query.topics.findFirst({
    where: eq(tables.topics.id, id),
    with: { chats: { with: { messages: true } } }
  })

  if (!topic) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Topic space not found' })
  }

  // Mark status as generating
  await db.update(tables.topics).set({ status: 'generating' }).where(eq(tables.topics.id, id))

  function parsePartsText(parts: any): string {
    if (!parts) return ''
    let p = parts
    if (typeof parts === 'string') {
      try { p = JSON.parse(parts) } catch { return parts.trim() }
    }
    if (Array.isArray(p)) {
      return p.map((item: any) => (typeof item === 'string' ? item : item.text || item.content || '')).filter(Boolean).join(' ')
    }
    return String(p).trim()
  }

  // Extract all discussion text across all chats in this topic
  let discussionText = ''
  if (topic.chats && Array.isArray(topic.chats)) {
    const allMsgs: string[] = []
    for (const c of topic.chats) {
      if (c.messages && Array.isArray(c.messages)) {
        for (const m of c.messages) {
          const txt = parsePartsText(m.parts)
          if (txt) {
            // Only skip messages that are purely system/internal JSON, not user content that happens to start with [ or {
            const trimmed = txt.trim()
            if (trimmed.startsWith('[System') || trimmed.startsWith('[Internal') || trimmed.startsWith('[system') || trimmed === '[object Object]') continue
            // Strip leading brackets/braces for cleaner content
            const cleanTxt = trimmed.replace(/^[[\]{}]+/, '').trim() || trimmed
            if (cleanTxt.length >= 2) {
              allMsgs.push(`${m.role === 'user' ? '问' : '答'}: ${cleanTxt}`)
            }
          }
        }
      }
    }
    discussionText = allMsgs.join('\n')
  }

  if (!discussionText.trim()) {
    discussionText = topic.title || '话题研读与分析'
  }

  const existingInfo = {
    title: topic.title,
    description: topic.description,
    soulContent: topic.soulContent,
    tags: topic.tags
  }

  function isPlaceholderTitle(t?: string): boolean {
    if (!t) return true
    const s = t.trim().toLowerCase()
    if (!s || s === '新对话' || s === 'untitled' || s === '新话题研读空间' || s === '话题研读空间') return true
    if (s.startsWith('我想知道') || s.startsWith('请问') || s.startsWith('问:') || s.startsWith('问：') || s.endsWith('...')) return true
    if (s.length <= 5 && !s.includes(' ')) return true
    return false
  }

  const customTitle = isPlaceholderTitle(topic.title) ? undefined : topic.title

  // Invoke Data Persistence Summarizer Infrastructure Service
  const res = await requestTopicSummarizerFromPersistence(id, discussionText, customTitle, existingInfo)

  const diskData = loadTopicFromDisk(id)
  const finalTitle = res?.title || diskData?.topicInfo?.title || topic.title
  const finalSoul = res?.soulContent || diskData?.soulContent || topic.soulContent
  const finalTags = res?.tags || diskData?.topicInfo?.tags || topic.tags || []
  const finalDesc = res?.description || diskData?.topicInfo?.description || ''

  const [updated] = await db.update(tables.topics).set({
    title: finalTitle,
    soulContent: finalSoul,
    description: finalDesc,
    tags: finalTags,
    status: 'ready'
  }).where(eq(tables.topics.id, id)).returning()

  syncTopicToDisk(id, { ...updated, description: finalDesc }, finalSoul, [])

  return {
    ...updated,
    description: finalDesc
  }
})
