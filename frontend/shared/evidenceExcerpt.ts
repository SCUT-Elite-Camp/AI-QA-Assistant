const confluenceLocalId = /<!--\s*confluence-local-id:\s*[a-f0-9]+\s*-->/gi

export function stripConfluenceLocalIds(value: string): string {
  return value.replace(confluenceLocalId, '')
}

export function normalizedEvidenceExcerpt(value: string): string {
  return stripConfluenceLocalIds(value).replace(/\s+/g, ' ').trim()
}

// A table slice can repeat its header or label a source row, so it need not be
// contiguous in the full rendered body. Accept only the exact current chunk
// returned by the already permission/version/hash-checked source backend.
export function matchesAuthoritativeChunk(source: { chunks?: unknown }, excerpt: string, chunkId: string): boolean {
  if (!chunkId || !excerpt.trim() || !Array.isArray(source.chunks)) return false
  const matches = source.chunks.filter((chunk: any) => chunk && String(chunk.chunk_id || '') === chunkId)
  return matches.length === 1 && String(matches[0].markdown_text || matches[0].text || '').trim() === excerpt.trim()
}

export function locateEvidenceExcerpt(source: string, excerpt: string): { start: number, end: number } | null {
  const readable = stripConfluenceLocalIds(source)
  const words = excerpt.trim().split(/\s+/).filter(Boolean)
  if (!words.length) return null
  const pattern = words.map(word => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+')
  const match = new RegExp(pattern).exec(readable)
  if (match) return { start: match.index, end: match.index + match[0].length }
  // Parser excerpts can omit Markdown code delimiters. Map an identical text
  // match back to the original body without removing any substantive tokens.
  const offsets: number[] = []
  let plain = ''
  let codeDelimiter = 0
  for (let index = 0; index < readable.length; index++) {
    // Structured table rows use real newlines where authoritative Markdown
    // renders an HTML break. Preserve its body offset and all cell contents.
    if (!codeDelimiter && readable[index] === '<') {
      const lineBreak = /^<br\s*\/?>/i.exec(readable.slice(index))
      if (lineBreak) {
        offsets.push(index)
        plain += ' '
        index += lineBreak[0].length - 1
        continue
      }
    }
    if (readable[index] === '`') {
      let length = 1
      while (readable[index + length] === '`') length++
      if (codeDelimiter === 0 || codeDelimiter === length) {
        codeDelimiter = codeDelimiter === 0 ? length : 0
        index += length - 1
        continue
      }
    }
    if (!codeDelimiter && readable[index] === '\\' && /[\\`*_[\]{}()#+\-.!|<>]/.test(readable[index + 1] || '')) index++
    offsets.push(index)
    plain += readable[index]
  }
  const plainWords = excerpt.replace(/`/g, '').trim().split(/\s+/).filter(Boolean)
  if (!plainWords.length) return null
  const plainPattern = plainWords.map(word => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+')
  const plainMatch = new RegExp(plainPattern).exec(plain)
  return plainMatch ? { start: offsets[plainMatch.index]!, end: offsets[plainMatch.index + plainMatch[0].length - 1]! + 1 } : null
}
