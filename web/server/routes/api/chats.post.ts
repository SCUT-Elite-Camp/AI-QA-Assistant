import { defineHandler, HTTPError } from 'nitro'
import { readValidatedBody } from 'nitro/h3'
import { z } from 'zod'
import { inArray } from 'drizzle-orm'
import { useDrizzle, tables } from '../../utils/drizzle'
import { appendMessage } from '../../utils/messageLifecycle'
import { requireAttachmentAccess } from '../../utils/attachmentAccess'
import { attachmentServiceJson } from '../../utils/attachmentService'
import { requirePrincipal } from '../../utils/attachmentAuth'
import { mergeSafeAttachmentParts } from '../../../shared/utils/attachmentParts'
import { canBindDraftToNewChat } from '../../../shared/utils/attachmentScope'

export default defineHandler(async (event) => {
  const userId = await requirePrincipal(event)

  const {
    input: rawInput,
    attachment_ids: attachmentIds,
    accepted_needs_review_ids: acceptedReviewIds,
    knowledge_base_retrieval_enabled: useKnowledgeBase,
    exploration_mode: explorationMode,
  } = await readValidatedBody(event, z.object({
    input: z.string().default(''),
    attachment_ids: z.array(z.string().startsWith('att_')).max(10).default([]),
    accepted_needs_review_ids: z.array(z.string().startsWith('att_')).max(10).default([]),
    knowledge_base_retrieval_enabled: z.boolean().default(true),
    exploration_mode: z.enum(['auto', 'off', 'force']).default('auto'),
  }).parse)
  const db = useDrizzle()

  for (const attachmentId of attachmentIds) {
    await requireAttachmentAccess(event, attachmentId)
  }
  const selected = attachmentIds.length
    ? await db.query.attachments.findMany({
        where: inArray(tables.attachments.id, attachmentIds),
      })
    : []
  if (selected.length !== attachmentIds.length
    || selected.some(item => !canBindDraftToNewChat(item, userId))) {
    throw new HTTPError({ statusCode: 409, statusMessage: 'attachment_scope_mismatch' })
  }
  const acceptedReview = new Set(acceptedReviewIds)
  if (selected.some(item => item.status !== 'ready'
    && !(item.status === 'needs_review' && acceptedReview.has(item.id)))) {
    throw new HTTPError({ statusCode: 409, statusMessage: 'attachments_not_ready' })
  }

  const input = rawInput.trim() || (attachmentIds.length ? '请分析这些附件' : '')
  if (!input) {
    throw new HTTPError({ statusCode: 422, statusMessage: 'message_required' })
  }

  const cleanInput = input.trim()
  const initialTitle = cleanInput.length > 20 ? cleanInput.slice(0, 20) + '...' : (cleanInput || '新对话')

  const [chat] = await db.insert(tables.chats).values({
    title: initialTitle,
    userId
  }).returning()
  if (!chat) {
    throw new HTTPError({ statusCode: 500, statusMessage: 'Failed to create chat' })
  }

  const message = await appendMessage(db, {
    chatId: chat.id,
    role: 'user',
    parts: mergeSafeAttachmentParts([
      { type: 'text', text: input },
      {
        type: 'data-chat-preferences',
        data: {
          knowledge_base_retrieval_enabled: useKnowledgeBase,
          exploration_mode: explorationMode,
        },
      },
    ], selected, acceptedReview),
  })

  if (selected.length) {
    await Promise.all(selected.map(item => attachmentServiceJson(
      `/v1/attachments/${item.id}/scope`,
      {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          scope: 'chat',
          expires_at: Math.floor(
            (item.expiresAt?.getTime() || Date.now() + 86_400_000) / 1000,
          ),
        }),
      },
    )))
    await db.transaction(async (tx) => {
      await tx.insert(tables.messageAttachments).values(selected.map(item => ({
        messageId: message.id,
        attachmentId: item.id,
        evidenceVersion: item.evidenceVersion,
      }))).onConflictDoNothing()
      await tx.update(tables.attachments)
        .set({ scope: 'chat', chatId: chat.id })
        .where(inArray(tables.attachments.id, attachmentIds))
    })
  }

  return chat
})
