export type TopicRole = 'owner' | 'editor' | 'viewer'

export function topicCapabilities(isChatOwner: boolean, topicRole: TopicRole | null) {
  if (topicRole === null) {
    return {
      canChat: isChatOwner,
      canUploadAttachments: isChatOwner,
      canEditTopic: isChatOwner,
    }
  }
  const canEdit = topicRole === 'owner' || topicRole === 'editor'
  return {
    canChat: true,
    canUploadAttachments: canEdit,
    canEditTopic: canEdit,
  }
}
