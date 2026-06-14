<script setup>
import ChatMessage from './ChatMessage.vue';

defineProps({
  messages: {
    type: Array,
    default: () => [],
  },
  isSending: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits(['copy']);

function handleCopy(message) {
  emit('copy', message);
}
</script>

<template>
  <section class="chat-window" aria-label="聊天消息区" aria-live="polite">
    <div v-if="messages.length === 0" class="chat-empty">
      <div class="placeholder-title">聊天消息区</div>
      <p>暂无消息。输入一个问题后，这里会展示用户问题和助手回答。</p>
    </div>

    <div v-else class="message-list">
      <ChatMessage
        v-for="message in messages"
        :key="message.id"
        :message="message"
        @copy="handleCopy"
      />
    </div>
  </section>
</template>
