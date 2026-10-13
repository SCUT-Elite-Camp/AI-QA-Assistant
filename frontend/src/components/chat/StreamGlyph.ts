import { computed, defineComponent, h } from 'vue'

export default defineComponent({
  name: 'StreamGlyph',
  props: {
    text: { type: String, required: true },
    born: { type: Number, required: true },
    offset: { type: Number, required: true },
  },
  setup(props) {
    // Cache the initial age per glyph so a Markdown reparse does not restart its fade.
    const delay = computed(() => `${-Math.max(0, Date.now() - props.born)}ms`)
    return () => h('span', {
      key: `${props.offset}:${props.born}`,
      class: 'stream-glyph',
      style: { animationDelay: delay.value },
    }, props.text)
  }
})
