import { z } from 'zod'

export const answerClaimSchema = z.object({
  claim_id: z.string().min(1).max(100),
  text: z.string().min(1).max(40000),
  start: z.number().int().nonnegative(),
  end: z.number().int().positive(),
  supports: z.array(z.object({ citation_id: z.number().int().positive(), quote: z.string().min(1).max(6000).nullable() }).strict()).min(1).max(20),
}).strict()

export type AnswerClaim = z.infer<typeof answerClaimSchema>

/** Offsets count Unicode code points, matching Python. Old messages need no backfill. */
export function parseAnswerClaims(value: unknown, answer: string, citations: { citation_id?: number, index?: number, snippet?: string, chunk_text?: string }[]): AnswerClaim[] {
  const claims = z.array(answerClaimSchema).max(10000).parse(value)
  const chars = Array.from(answer)
  const refs = new Map(citations.map(item => [Number(item.citation_id ?? item.index), item]))
  let previousEnd = 0
  for (const claim of claims) {
    if (claim.start < previousEnd || claim.end <= claim.start || claim.end > chars.length
      || chars.slice(claim.start, claim.end).join('') !== claim.text) throw new Error('invalid_answer_claims')
    previousEnd = claim.end
    for (const support of claim.supports) {
      const source = refs.get(support.citation_id)
      const normalize = (text: string) => text.replace(/\s+/gu, ' ').trim()
      if (!source || (support.quote !== null && !normalize(source.snippet || source.chunk_text || '').includes(normalize(support.quote)))) {
        throw new Error('invalid_answer_claims')
      }
    }
  }
  return claims
}
