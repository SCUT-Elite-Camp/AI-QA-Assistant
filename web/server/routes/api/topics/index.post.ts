import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { readValidatedBody } from 'nitro/h3'
import { useUserSession } from '../../../utils/session'
import { useDrizzle, tables, eq } from '../../../utils/drizzle'
import { requestTopicSummarizerFromPersistence } from '../../../utils/soul'
import { syncTopicToDisk, loadTopicFromDisk } from '../../../utils/topicStorage'

export default defineHandler(async (event) => {
  const { chatId: inputChatId, title: customTitle } = await readValidatedBody(event, z.object({
    chatId: z.string().optional(),
    title: z.string().optional()
  }).parse)

  const db = useDrizzle()
  const session = await useUserSession(event)
  const userId = session.data.user?.id || session.id!

  let chat: any = null

  if (inputChatId) {
    chat = await db.query.chats.findFirst({
      where: eq(tables.chats.id, inputChatId),
      with: { messages: true }
    })
  } else {
    // Create new main chat for this topic space
    const [newChat] = await db.insert(tables.chats).values({
      title: customTitle?.trim() || '新话题研读空间',
      userId
    }).returning()
    chat = newChat
  }

  if (!chat) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Chat not found' })
  }

  // If chat already has a topic, return existing topic
  if (chat.topicId) {
    const existingTopic = await db.query.topics.findFirst({
      where: eq(tables.topics.id, chat.topicId)
    })
    if (existingTopic) {
      return existingTopic
    }
  }

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

  // Extract actual discussion content from chat messages
  let discussionText = ''
  if (chat.messages && Array.isArray(chat.messages) && chat.messages.length > 0) {
    const allMsgs: string[] = []
    for (const m of chat.messages) {
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
    discussionText = allMsgs.join('\n')
  }
  if (!discussionText || discussionText.trim() === 'Untitled' || discussionText.trim() === '新对话') {
    discussionText = chat.title || customTitle || 'Topic Workspace Analysis'
  }

  function cleanTitlePrefix(t?: string): string {
    if (!t) return ''
    let s = t.trim()
    for (const p of ['问:', '问：', '问: ', '问： ', '答:', '答：', '我想知道', '请问']) {
      if (s.startsWith(p)) s = s.slice(p.length).trim()
    }
    return s
  }

  function isPlaceholderTitle(t?: string): boolean {
    if (!t) return true
    const s = t.trim().toLowerCase()
    if (!s || s === '新对话' || s === 'untitled' || s === '新话题研读空间' || s === '话题研读空间' || s === 'topic workspace') return true
    if (s.startsWith('我想知道') || s.startsWith('请问') || s.startsWith('问:') || s.startsWith('问：') || s.endsWith('...')) return true
    if (s.length <= 5 && !s.includes(' ')) return true
    return false
  }

  const cleanCustomTitle = isPlaceholderTitle(customTitle) ? undefined : cleanTitlePrefix(customTitle)

  const topicId = crypto.randomUUID()
  const rawInitial = cleanTitlePrefix(customTitle) || cleanTitlePrefix(chat.title) || 'Topic Workspace'
  const initialTitle = rawInitial.length >= 2 ? rawInitial : 'Topic Workspace'

  // Insert topic record with initial generating status
  const [topic] = await db.insert(tables.topics).values({
    id: topicId,
    title: initialTitle,
    mainChatId: chat.id,
    soulContent: `# Topic Cognition: ${initialTitle}`,
    tags: [initialTitle.slice(0, 10)],
    status: 'generating',
    weightMode: 'auto',
    consecutiveNoNewDocsCount: 0
  }).returning()

  // Attach chat to topic
  await db.update(tables.chats).set({ topicId: topic.id }).where(eq(tables.chats.id, chat.id))

  // Trigger Data Persistence Layer Infrastructure Summarizer Service asynchronously in background
  requestTopicSummarizerFromPersistence(topicId, discussionText, cleanCustomTitle).then(async (result) => {
    const diskData = loadTopicFromDisk(topicId)
    const finalTitle = cleanTitlePrefix(result?.title || diskData?.topicInfo?.title) || initialTitle
    const finalSoul = result?.soulContent || diskData?.soulContent || `# Topic Cognition: ${finalTitle}`
    const finalTags = result?.tags || diskData?.topicInfo?.tags || [finalTitle.slice(0, 10)]
    const finalDesc = result?.description || diskData?.topicInfo?.description || ''

    const [updated] = await db.update(tables.topics).set({
      title: finalTitle,
      soulContent: finalSoul,
      tags: finalTags,
      description: finalDesc,
      status: 'ready'
    }).where(eq(tables.topics.id, topicId)).returning()

    syncTopicToDisk(topicId, { ...updated, description: finalDesc }, finalSoul, [])
  }).catch(async (err) => {
    console.error('[TopicSummarizer] Async summarization failed:', err)
    await db.update(tables.topics).set({ status: 'ready' }).where(eq(tables.topics.id, topicId)).execute()
  })

  // Return immediately to frontend (<50ms) with status: 'generating' so UI transitions smoothly
  return topic
})
