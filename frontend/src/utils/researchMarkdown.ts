/** Use Comark inline components so citations cannot swallow following prose. */
export function formatResearchCitations(markdown: string): string {
  return markdown.replace(/\[(\d+)]/g, ' :cite-mark{index="$1"} ')
}
import type { ResearchEvent } from '../types/research'

/** Progress summaries are bounded; conversation bodies retain their full text. */
export function researchConversationText(event: Pick<ResearchEvent, 'message' | 'payload'>): string {
  return typeof event.payload.content === 'string' ? event.payload.content : event.message
}
