import { nextTick, onScopeDispose, ref, watch, type Ref, type WatchSource } from 'vue'

/** Measure against the compact row, even while expanded, so layout never oscillates. */
export function useAdaptiveComposer(
  input: Ref<string>,
  textarea: Ref<HTMLTextAreaElement | undefined | null>,
  root: Ref<HTMLElement | null>,
  dependencies: WatchSource[] = [],
) {
  const multiline = ref(false)
  let context: CanvasRenderingContext2D | null = null

  function measure() {
    const container = root.value
    const field = textarea.value
    if (!container || !field) return
    if (/\r|\n/.test(input.value)) {
      multiline.value = true
      return
    }
    context ??= document.createElement('canvas').getContext('2d')
    if (!context) return
    const style = getComputedStyle(field)
    context.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`
    const controls = [...container.querySelectorAll<HTMLElement>('[data-composer-control]')]
    const controlWidth = controls.reduce((total, control) => total + control.getBoundingClientRect().width, 0)
    const columns = Number(container.dataset.compactColumns || 3)
    const gap = parseFloat(getComputedStyle(container).columnGap) || 0
    const textPadding = (parseFloat(style.paddingLeft) || 0) + (parseFloat(style.paddingRight) || 0)
    const available = container.clientWidth - controlWidth - gap * (columns - 1) - textPadding
    const spacing = parseFloat(style.letterSpacing) || 0
    const textWidth = context.measureText(input.value).width + Math.max(0, [...input.value].length - 1) * spacing
    multiline.value = Boolean(input.value) && textWidth > Math.max(0, available - 4)
  }

  watch([input, textarea, root, ...dependencies], async () => {
    await nextTick()
    measure()
  }, { flush: 'post' })
  let observer: ResizeObserver | undefined
  watch([root, ...dependencies], async () => {
    await nextTick()
    observer?.disconnect()
    if (!root.value || typeof ResizeObserver === 'undefined') return
    observer = new ResizeObserver(measure)
    observer.observe(root.value)
    root.value.querySelectorAll<HTMLElement>('[data-composer-control]').forEach(control => observer!.observe(control))
  }, { flush: 'post' })
  onScopeDispose(() => observer?.disconnect())
  return multiline
}
