import { describe, expect, it } from 'vitest'
import { locateEvidenceExcerpt, normalizedEvidenceExcerpt, stripConfluenceLocalIds } from '../shared/evidenceExcerpt'

describe('authorized source excerpt matching', () => {
  it('ignores only exporter local ID comments between authoritative Markdown blocks', () => {
    const source = '# Meeting\n\n<!-- confluence-local-id: 789429891717 -->\nHi all,\n\n<!-- confluence-local-id: 1dcc288a1883 -->\nAction item'
    expect(normalizedEvidenceExcerpt(source)).toContain(normalizedEvidenceExcerpt('# Meeting\n\nHi all,\n\nAction item'))
    expect(stripConfluenceLocalIds(source)).toContain('# Meeting\n\n\nHi all,')
    expect(locateEvidenceExcerpt(source, '# Meeting\n\nHi all,\n\nAction item')).not.toBeNull()
    expect(locateEvidenceExcerpt(source, 'unrelated claim')).toBeNull()
    expect(normalizedEvidenceExcerpt('<!-- other annotation -->')).toBe('<!-- other annotation -->')
  })

  it('locates parser text across inline code while preserving substantive tokens and body offsets', () => {
    const source = '# Design\n\nBFF validates `evidence.provenance.v1` and the evidence\\_ref.\n\nLater section'
    const range = locateEvidenceExcerpt(source, 'BFF validates evidence.provenance.v1 and the evidence_ref.')!
    expect(source.slice(range.start, range.end)).toBe('BFF validates `evidence.provenance.v1` and the evidence\\_ref.')
    expect(locateEvidenceExcerpt(source, 'BFF validates evidence.provenance.v2 and the evidence_ref.')).toBeNull()
    expect(locateEvidenceExcerpt('path/[id]/source', 'path/id/source')).toBeNull()
    expect(locateEvidenceExcerpt('Use `C:\\_temp`.', 'Use C:_temp.')).toBeNull()
  })

  it('locates multiline table cells without changing numbers, column order or literal code', () => {
    const source = '| Top1:att<br>mAP: att | 46.3<BR />46.9 | 56.9<br/>58.0 |'
    const excerpt = 'Top1:att\nmAP: att | 46.3\n46.9 | 56.9\n58.0'
    const range = locateEvidenceExcerpt(source, excerpt)!
    expect(source.slice(range.start, range.end)).toBe(source.slice(2, -2))
    expect(locateEvidenceExcerpt(source, excerpt.replace('46.3', '46.4'))).toBeNull()
    expect(locateEvidenceExcerpt(source, 'Top1:att mAP: att | 56.9 58.0 | 46.3 46.9')).toBeNull()
    expect(locateEvidenceExcerpt('Literal `A<br>B` token', 'Literal A B token')).toBeNull()
    expect(locateEvidenceExcerpt('A<br data-id="x">B', 'A B')).toBeNull()
  })
})
