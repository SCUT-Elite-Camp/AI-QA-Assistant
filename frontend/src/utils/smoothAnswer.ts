/// <reference lib="es2022.intl" />

export interface SmoothAnswerView {
  messageId: string
  text: string
  pending: boolean
}

interface Options {
  onUpdate: (view: SmoothAnswerView | null) => void
  requestFrame?: (callback: FrameRequestCallback) => number
  cancelFrame?: (id: number) => void
  instant?: () => boolean
}

/** Presentation only: receives checked text and never changes the saved answer. */
export function createSmoothAnswer(options: Options) {
  const requestFrame = options.requestFrame ?? (callback => requestAnimationFrame(callback))
  const cancelFrame = options.cancelFrame ?? (id => cancelAnimationFrame(id))
  const segmenter = new Intl.Segmenter(undefined, { granularity: 'grapheme' })
  let active: {
    messageId: string; target: string; ends: number[]; shown: number
    final: boolean; committed: boolean
  } | null = null
  let frame: number | null = null
  let previousTime: number | undefined
  let credit = 0

  function stopFrame() {
    if (frame !== null) cancelFrame(frame)
    frame = null
    previousTime = undefined
    credit = 0
  }

  function publish() {
    if (!active) return
    if (active.final && active.committed && active.shown === active.ends.length) {
      active = null
      stopFrame()
      options.onUpdate(null)
      return
    }
    options.onUpdate({
      messageId: active.messageId,
      text: active.target.slice(0, active.ends[active.shown - 1] ?? 0),
      pending: active.shown < active.ends.length
    })
  }

  function setTarget(text: string) {
    if (!active) return
    // Do not display half a UTF-16 surrogate if a transport splits an emoji.
    const segmentable = /[\uD800-\uDBFF]$/.test(text) ? text.slice(0, -1) : text
    active.target = text
    active.ends = Array.from(segmenter.segment(segmentable), part => part.index + part.segment.length)
  }

  function schedule() {
    if (!active || frame !== null || active.shown === active.ends.length) return
    if (options.instant?.()) {
      active.shown = active.ends.length
      publish()
      return
    }
    const turn = active
    frame = requestFrame(time => {
      if (active !== turn) return // A cancelled/replaced turn cannot paint later.
      frame = null
      const elapsed = previousTime === undefined ? 1000 / 60 : Math.max(0, Math.min(48, time - previousTime))
      previousTime = time
      const remaining = turn.ends.length - turn.shown
      const rate = remaining > 1200 ? 240 : remaining > 300 ? 160 : remaining > 80 ? 100 : 60
      credit = Math.min(4, credit + elapsed * rate / 1000)
      const step = Math.min(remaining, Math.floor(credit))
      turn.shown += step
      credit -= step
      publish()
      if (active && active.shown < active.ends.length) schedule()
      else { previousTime = undefined; credit = 0 }
    })
  }

  function cancel() {
    active = null
    stopFrame()
    options.onUpdate(null)
  }

  function begin(messageId: string) {
    cancel()
    active = { messageId, target: '', ends: [], shown: 0, final: false, committed: false }
    publish()
  }

  function append(messageId: string, delta: string) {
    if (active?.messageId !== messageId) begin(messageId)
    if (!active || active.final) return
    setTarget(active.target + delta)
    publish()
    schedule()
  }

  function finish(messageId: string, text: string) {
    if (active?.messageId !== messageId) begin(messageId)
    if (!active) return
    const visible = active.target.slice(0, active.ends[active.shown - 1] ?? 0)
    const before = Array.from(segmenter.segment(visible), part => part.segment)
    const after = Array.from(segmenter.segment(text), part => part.segment)
    let common = 0
    while (common < before.length && before[common] === after[common]) common++
    // A quality repair replaces its differing suffix immediately; discard old queued text.
    active.shown = common
    active.final = true
    setTarget(text)
    publish()
    schedule()
  }

  function commit(messageId: string) {
    if (active?.messageId !== messageId) return
    active.committed = true
    publish()
  }

  function flushFinal() {
    if (!active?.final || !active.committed) return false
    active.shown = active.ends.length
    publish()
    return true
  }

  return { begin, append, finish, commit, cancel, flushFinal }
}
