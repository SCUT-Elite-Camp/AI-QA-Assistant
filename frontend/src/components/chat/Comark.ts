import { defineComarkComponent } from '@comark/vue'
import { defineComponent, h } from 'vue'
import highlight from '@comark/vue/plugins/highlight'
import html from '@shikijs/langs/html'
import css from '@shikijs/langs/css'
import python from '@shikijs/langs/python'
import sql from '@shikijs/langs/sql'
import go from '@shikijs/langs/go'
import rust from '@shikijs/langs/rust'
import java from '@shikijs/langs/java'
import c from '@shikijs/langs/c'
import cpp from '@shikijs/langs/cpp'
import ruby from '@shikijs/langs/ruby'
import php from '@shikijs/langs/php'
import swift from '@shikijs/langs/swift'
import kotlin from '@shikijs/langs/kotlin'
import diff from '@shikijs/langs/diff'
import dockerfile from '@shikijs/langs/dockerfile'
import xml from '@shikijs/langs/xml'
import toml from '@shikijs/langs/toml'
import graphql from '@shikijs/langs/graphql'
import SourceLink from './SourceLink.vue'
import CiteMark from './CiteMark.vue'
import StreamGlyph from './StreamGlyph'
import { createStreamTextFade } from '../../utils/streamTextFade'

const Markdown = defineComarkComponent({
  name: 'ChatComark',
  plugins: [
    highlight({
      languages: [html, css, python, sql, go, rust, java, c, cpp, ruby, php, swift, kotlin, diff, dockerfile, xml, toml, graphql]
    })
  ],
  components: {
    'source-link': SourceLink,
    'cite-mark': CiteMark,
    'stream-glyph': StreamGlyph,
  },
  class: 'markdown-body comark-content *:first:mt-0 *:last:mb-0'
})

export default defineComponent({
  name: 'ChatComark',
  props: {
    markdown: String,
    streaming: Boolean,
  },
  setup(props, { attrs, slots }) {
    const fade = createStreamTextFade(() => props.streaming)
    return () => h(Markdown, { ...attrs, ...props, plugins: [fade] }, slots)
  }
})

