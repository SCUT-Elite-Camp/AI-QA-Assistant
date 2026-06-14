<script setup>
import { computed } from 'vue';

const props = defineProps({
  citations: {
    type: Array,
    default: () => [],
  },
});

const normalizedCitations = computed(() => (
  Array.isArray(props.citations) ? props.citations : []
));

const hasCitations = computed(() => normalizedCitations.value.length > 0);

function hasSourceUrl(citation) {
  return Boolean(String(citation?.source_url || '').trim());
}

function formatScore(score) {
  if (typeof score !== 'number') {
    return '-';
  }

  return score.toFixed(2);
}

function citationKey(citation, index) {
  return citation?.citation_id || `${citation?.doc_id || 'doc'}-${citation?.chunk_id || index}`;
}
</script>

<template>
  <section v-if="hasCitations" class="citation-list" aria-label="引用来源">
    <h3 class="citation-list__title">引用来源</h3>
    <ol class="citation-list__items">
      <li
        v-for="(citation, index) in normalizedCitations"
        :key="citationKey(citation, index)"
        class="citation-card"
      >
        <div class="citation-card__header">
          <span class="citation-card__id">#{{ citation.citation_id ?? index + 1 }}</span>
          <a
            v-if="hasSourceUrl(citation)"
            class="citation-card__title citation-card__link"
            :href="citation.source_url"
            target="_blank"
            rel="noopener noreferrer"
          >
            {{ citation.title || '未命名引用' }}
          </a>
          <span v-else class="citation-card__title">
            {{ citation.title || '未命名引用' }}
          </span>
        </div>

        <dl class="citation-meta">
          <div>
            <dt>doc_id</dt>
            <dd>{{ citation.doc_id || '-' }}</dd>
          </div>
          <div>
            <dt>chunk_id</dt>
            <dd>{{ citation.chunk_id || '-' }}</dd>
          </div>
          <div>
            <dt>score</dt>
            <dd>{{ formatScore(citation.score) }}</dd>
          </div>
          <div v-if="!hasSourceUrl(citation)">
            <dt>source_url</dt>
            <dd>无外部链接</dd>
          </div>
        </dl>

        <p v-if="citation.snippet" class="citation-snippet">
          {{ citation.snippet }}
        </p>
      </li>
    </ol>
  </section>
</template>
