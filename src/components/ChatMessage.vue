<script setup>
import { computed } from 'vue';
import CitationList from './CitationList.vue';

const props = defineProps({
  message: {
    type: Object,
    required: true,
  },
});

const emit = defineEmits(['copy']);

const isAssistant = computed(() => props.message.role === 'assistant');
const roleLabel = computed(() => (isAssistant.value ? '助手' : '用户'));
const hasContent = computed(() => Boolean(props.message.content));
const hasCitations = computed(() => Boolean(props.message.citations?.length));

function handleCopy() {
  emit('copy', props.message);
}
</script>

<template>
  <article
    class="chat-message"
    :class="[
      message.role === 'user' ? 'chat-message--user' : 'chat-message--assistant',
      { 'chat-message--error': message.error, 'chat-message--loading': message.loading },
    ]"
  >
    <div class="message-meta">
      <span class="role-label">{{ roleLabel }}</span>
      <span v-if="message.loading" class="message-status">生成中...</span>
      <span v-else-if="message.error" class="message-status message-status--error">异常</span>
      <span v-else-if="isAssistant" class="message-status">完成</span>
    </div>

    <p class="message-content">
      <template v-if="hasContent">{{ message.content }}</template>
      <template v-else-if="message.loading">生成中...</template>
      <template v-else>暂无内容</template>
    </p>

    <div v-if="isAssistant" class="message-footer">
      <button
        v-if="hasContent"
        class="copy-button"
        type="button"
        title="复制回答"
        @click="handleCopy"
      >
        复制回答
      </button>
      <span v-if="message.trace_id" class="trace-id">trace_id: {{ message.trace_id }}</span>
    </div>

    <CitationList
      v-if="isAssistant && hasCitations"
      :citations="message.citations"
    />
  </article>
</template>
