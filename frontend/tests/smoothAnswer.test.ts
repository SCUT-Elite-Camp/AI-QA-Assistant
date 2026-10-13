import { describe, expect, it } from 'vitest'
import { createSmoothAnswer, type SmoothAnswerView } from '../src/utils/smoothAnswer'

function fixture(instant = false) {
  let view: SmoothAnswerView | null = null
  let id = 0
  let time = 0
  const frames = new Map<number, FrameRequestCallback>()
  const updates: (SmoothAnswerView | null)[] = []
  const answer = createSmoothAnswer({
    onUpdate: value => { view = value; updates.push(value) },
    requestFrame: callback => { frames.set(++id, callback); return id },
    cancelFrame: key => { frames.delete(key) },
    instant: () => instant,
  })
  function tick(elapsed = 1000 / 60) {
    time += elapsed
    const ready = [...frames.values()]
    frames.clear()
    ready.forEach(callback => callback(time))
  }
  function drain() {
    for (let count = 0; frames.size && count < 3000; count++) tick()
    expect(frames.size).toBe(0)
  }
  return { answer, tick, drain, frames, updates, get view() { return view } }
}

describe('smooth streamed answer presentation', () => {
  it('queues provider bursts and caps each paint at four graphemes, even after a stalled frame', () => {
    const f = fixture()
    const text = '中'.repeat(1500)
    f.answer.append('a', text)
    expect(f.view?.text).toBe('')
    f.tick()
    expect(f.view?.text).toBe('中'.repeat(4))
    f.tick(2000)
    expect(f.view?.text).toBe('中'.repeat(8))
    f.answer.append('a', ' end')
    expect(f.view?.text).toBe('中'.repeat(8))
    f.drain()
    expect(f.view).toEqual({ messageId: 'a', text: `${text} end`, pending: false })
    const lengths = f.updates.filter(Boolean).map(value => value!.text.length)
    expect(lengths.every((length, i) => !i || length - lengths[i - 1]! <= 4)).toBe(true)
  })

  it('keeps emoji, combining accents and split UTF-16 surrogates intact', () => {
    const f = fixture()
    f.answer.append('a', '你👨‍👩‍👧‍👦e\u0301\uD83D')
    f.tick()
    expect(f.view?.text).toBe('你')
    f.tick()
    expect(f.view?.text).toBe('你👨‍👩‍👧‍👦')
    f.drain()
    expect(f.view?.text).toBe('你👨‍👩‍👧‍👦e\u0301')
    f.answer.append('a', '\uDE00')
    f.drain()
    expect(f.view?.text).toBe('你👨‍👩‍👧‍👦e\u0301😀')
  })

  it('keeps smoothing the verified final answer after persistence completes', () => {
    const f = fixture()
    f.answer.append('a', 'hello world')
    f.tick()
    expect(f.view?.text).toBe('h')
    f.answer.finish('a', 'hello world!')
    f.answer.commit('a')
    expect(f.view?.text).toBe('h')
    expect(f.view?.pending).toBe(true)
    f.drain()
    expect(f.view).toBeNull()
    expect(f.updates.at(-2)?.text).toBe('hello world')
  })

  it('holds a fully painted preview until the canonical SDK message is committed', () => {
    const f = fixture()
    f.answer.finish('a', 'final')
    f.drain()
    expect(f.view?.text).toBe('final')
    f.answer.commit('other')
    expect(f.view?.text).toBe('final')
    f.answer.commit('a')
    expect(f.view).toBeNull()
  })

  it('discards the old queue and removes a differing draft suffix on final quality repair', () => {
    const f = fixture()
    f.answer.append('a', 'same WRONG long draft')
    for (let i = 0; i < 8; i++) f.tick()
    expect(f.view?.text).toBe('same WRO')
    f.answer.finish('a', 'same CORRECT')
    expect(f.view?.text).toBe('same ')
    f.answer.append('a', 'late old delta')
    f.drain()
    expect(f.view?.text).toBe('same CORRECT')
  })

  it('cancels all queued text on stop, failure or unmount and ignores stale callbacks', () => {
    const f = fixture()
    f.answer.append('old', 'queued secret')
    const stale = [...f.frames.values()][0]!
    f.answer.cancel()
    expect(f.view).toBeNull()
    expect(f.frames.size).toBe(0)
    f.answer.append('new', 'safe')
    stale(1000)
    expect(f.view).toEqual({ messageId: 'new', text: '', pending: true })
    f.drain()
    expect(f.view?.text).toBe('safe')
  })

  it('allows Stop to finish only a verified and committed answer without losing saved text', () => {
    const f = fixture()
    f.answer.append('a', 'draft')
    expect(f.answer.flushFinal()).toBe(false)
    f.answer.finish('a', 'checked answer')
    expect(f.answer.flushFinal()).toBe(false)
    f.answer.commit('a')
    expect(f.answer.flushFinal()).toBe(true)
    expect(f.view).toBeNull()
    expect(f.frames.size).toBe(0)
  })

  it('supports instant presentation for reduced motion or a hidden tab', () => {
    const f = fixture(true)
    f.answer.append('a', 'complete chunk')
    expect(f.view?.text).toBe('complete chunk')
    expect(f.frames.size).toBe(0)
    f.answer.finish('a', 'verified')
    f.answer.commit('a')
    expect(f.view).toBeNull()
  })
})
