/** Use Comark inline components so citations cannot swallow following prose. */
export function formatResearchCitations(markdown: string, availableIndices?: ReadonlySet<number>): string {
  // A live model may not have emitted the closing fence/backtick yet.
  return markdown.replace(/(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`[^`\n]*(?:`|$))|\[(\d+(?:\s*,\s*\d+)*)\]/g, (match, code, digits) => {
    if (code || !digits) return match
    if (availableIndices && digits.split(',').some((number: string) => !availableIndices.has(Number(number.trim())))) return match
    return ` ${digits.split(',').map((number: string) => `:cite-mark{index="${number.trim()}"}`).join(' ')} `
  })
}
import type { ResearchEvent } from '../types/research'

/** Progress summaries are bounded; conversation bodies retain their full text. */
export function researchConversationText(event: Pick<ResearchEvent, 'message' | 'payload'>): string {
  return typeof event.payload.content === 'string' ? event.payload.content : event.message
}
