import { describe, expect, it } from 'vitest'
import {
  attachmentBatchExpired,
  canBindDraftToNewChat,
  canSelectAttachmentForChat,
  isAnonymousAttachmentPrincipal,
  validBatchReferences,
} from '../shared/utils/attachmentScope'

describe('attachment scope contracts', () => {
  it('requires exactly the identifiers belonging to the selected batch scope', () => {
    expect(validBatchReferences('draft')).toBe(true)
    expect(validBatchReferences('draft', 'chat-1')).toBe(false)
    expect(validBatchReferences('chat', 'chat-1')).toBe(true)
    expect(validBatchReferences('chat', 'chat-1', 'topic-1')).toBe(true)
    expect(validBatchReferences('topic', null, 'topic-1')).toBe(true)
    expect(validBatchReferences('topic', null, null)).toBe(false)
  })

  it('only binds an unbound draft owned by the new chat owner', () => {
    expect(canBindDraftToNewChat({ scope: 'draft', ownerId: 'user-1', chatId: null, topicId: null }, 'user-1')).toBe(true)
    expect(canBindDraftToNewChat({ scope: 'topic', ownerId: 'user-1', chatId: null, topicId: 'topic-1' }, 'user-1')).toBe(false)
    expect(canBindDraftToNewChat({ scope: 'draft', ownerId: 'user-2', chatId: null, topicId: null }, 'user-1')).toBe(false)
  })

  it('prevents chat attachments crossing chats and topic attachments crossing topics', () => {
    expect(canSelectAttachmentForChat({ scope: 'chat', ownerId: 'u', chatId: 'chat-1', topicId: null }, 'chat-1', null)).toBe(true)
    expect(canSelectAttachmentForChat({ scope: 'chat', ownerId: 'u', chatId: 'chat-2', topicId: null }, 'chat-1', null)).toBe(false)
    expect(canSelectAttachmentForChat({ scope: 'topic', ownerId: 'u', chatId: null, topicId: 'topic-1' }, 'chat-1', 'topic-1')).toBe(true)
    expect(canSelectAttachmentForChat({ scope: 'topic', ownerId: 'u', chatId: null, topicId: 'topic-2' }, 'chat-1', 'topic-1')).toBe(false)
    expect(canSelectAttachmentForChat({ scope: 'draft', ownerId: 'u', chatId: null, topicId: null }, 'chat-1', null)).toBe(false)
  })

  it('recognizes expired batches and development anonymous principals', () => {
    expect(attachmentBatchExpired(new Date(1_000), new Date(1_001))).toBe(true)
    expect(attachmentBatchExpired(null, new Date())).toBe(false)
    expect(isAnonymousAttachmentPrincipal('anonymous:session')).toBe(true)
    expect(isAnonymousAttachmentPrincipal('user-1')).toBe(false)
  })
})
