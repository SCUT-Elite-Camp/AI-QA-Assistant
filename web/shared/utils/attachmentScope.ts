export type AttachmentScope = 'draft' | 'chat' | 'topic'

export interface AttachmentScopeRecord {
  scope: AttachmentScope
  ownerId: string
  chatId: string | null
  topicId: string | null
}

export function validBatchReferences(
  scope: AttachmentScope,
  chatId?: string | null,
  topicId?: string | null,
): boolean {
  if (scope === 'draft') return !chatId && !topicId
  if (scope === 'chat') return !!chatId
  return !!topicId && !chatId
}

export function isAnonymousAttachmentPrincipal(userId: string): boolean {
  return userId.startsWith('anonymous:')
}

export function canBindDraftToNewChat(attachment: AttachmentScopeRecord, userId: string): boolean {
  return attachment.scope === 'draft'
    && attachment.ownerId === userId
    && !attachment.chatId
    && !attachment.topicId
}

export function canSelectAttachmentForChat(
  attachment: AttachmentScopeRecord,
  chatId: string,
  topicId: string | null,
): boolean {
  if (attachment.scope === 'chat') return attachment.chatId === chatId
  if (attachment.scope === 'topic') return !!topicId && attachment.topicId === topicId
  return false
}

export function attachmentBatchExpired(expiresAt: Date | null, now = new Date()): boolean {
  return !!expiresAt && expiresAt.getTime() <= now.getTime()
}
