export interface SafeAttachmentRecord {
  id: string
  filename: string
  mimeType: string
  status: string
}

export function extractAttachmentSelection(parts: unknown, metadata: unknown = {}): {
  attachmentIds: string[]
  acceptedNeedsReviewIds: string[]
} {
  const safeParts = Array.isArray(parts) ? parts : []
  const safeMetadata = metadata && typeof metadata === 'object' ? metadata as Record<string, unknown> : {}
  const partIds: string[] = []
  const acceptedPartIds: string[] = []
  for (const part of safeParts) {
    if (!part || typeof part !== 'object' || (part as any).type !== 'data-attachment') continue
    const data = (part as any).data
    const id = typeof data?.attachment_id === 'string' ? data.attachment_id : ''
    if (!id.startsWith('att_')) continue
    partIds.push(id)
    if (data.accepted_review === true) acceptedPartIds.push(id)
  }
  const metadataIds = Array.isArray(safeMetadata.attachmentIds)
    ? safeMetadata.attachmentIds.filter((value): value is string => typeof value === 'string' && value.startsWith('att_'))
    : []
  const acceptedMetadataIds = Array.isArray(safeMetadata.acceptedNeedsReviewIds)
    ? safeMetadata.acceptedNeedsReviewIds.filter((value): value is string => typeof value === 'string' && value.startsWith('att_'))
    : []
  return {
    attachmentIds: Array.from(new Set([...metadataIds, ...partIds])).slice(0, 10),
    acceptedNeedsReviewIds: Array.from(new Set([...acceptedMetadataIds, ...acceptedPartIds])).slice(0, 10),
  }
}

export function mergeSafeAttachmentParts(
  parts: unknown,
  attachments: SafeAttachmentRecord[],
  acceptedNeedsReviewIds: ReadonlySet<string>,
): any[] {
  const nonAttachmentParts = (Array.isArray(parts) ? parts : []).filter(
    part => !part || typeof part !== 'object' || (part as any).type !== 'data-attachment',
  )
  return [
    ...nonAttachmentParts,
    ...attachments.map(item => ({
      type: 'data-attachment',
      data: {
        attachment_id: item.id,
        filename: item.filename,
        mime_type: item.mimeType,
        status: item.status,
        accepted_review: item.status === 'needs_review' && acceptedNeedsReviewIds.has(item.id),
      },
    })),
  ]
}
