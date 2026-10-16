import { describe, expect, it } from 'vitest'
import { matchesAuthoritativeChunk } from '../shared/evidenceExcerpt'

describe('current authoritative chunk excerpts', () => {
  const text = 'Test Cases\n| Test ID | Duration |\n| --- | --- |\n| AR-005 | 14 |'
  const source = { chunks: [{ chunk_id: 'report_chunk_2', text }] }
  it('accepts a current table slice only with its exact chunk identity', () => {
    expect(matchesAuthoritativeChunk(source, text, 'report_chunk_2')).toBe(true)
    expect(matchesAuthoritativeChunk(source, text, 'other_chunk')).toBe(false)
    expect(matchesAuthoritativeChunk(source, text, '')).toBe(false)
  })
  it('rejects changed values and swapped row/column bindings', () => {
    expect(matchesAuthoritativeChunk(source, text.replace('14', '12'), 'report_chunk_2')).toBe(false)
    expect(matchesAuthoritativeChunk(source, text.replace('AR-005 | 14', '14 | AR-005'), 'report_chunk_2')).toBe(false)
  })
  it('rejects missing projection data and arbitrary body text', () => {
    expect(matchesAuthoritativeChunk({}, text, 'report_chunk_2')).toBe(false)
    expect(matchesAuthoritativeChunk(source, 'Test Cases', 'report_chunk_2')).toBe(false)
  })
})
