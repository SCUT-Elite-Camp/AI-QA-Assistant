<script setup>
const props = defineProps({
  modelValue: {
    type: String,
    default: '',
  },
  isSending: {
    type: Boolean,
    default: false,
  },
  canSend: {
    type: Boolean,
    default: false,
  },
  inputError: {
    type: String,
    default: '',
  },
});

const emit = defineEmits(['update:modelValue', 'send']);

function handleInput(event) {
  emit('update:modelValue', event.target.value);
}

function handleKeydown(event) {
  if (event.key !== 'Enter' || event.shiftKey) {
    return;
  }

  event.preventDefault();
  handleSend();
}

function handleSend() {
  if (props.isSending) {
    return;
  }

  emit('send');
}
</script>

<template>
  <section class="chat-input" aria-label="问题输入区">
    <label class="input-label" for="chat-input-textarea">问题输入区</label>
    <textarea
      id="chat-input-textarea"
      class="chat-input__textarea"
      :value="modelValue"
      rows="3"
      :disabled="isSending"
      placeholder="请输入自然语言问题"
      @input="handleInput"
      @keydown="handleKeydown"
    />
    <p v-if="inputError" class="input-error" role="alert">{{ inputError }}</p>
    <div class="input-actions">
      <button
        class="primary-button"
        :class="{ 'primary-button--ready': canSend }"
        type="button"
        :disabled="isSending"
        :title="canSend ? '发送问题' : '请输入有效问题'"
        @click="handleSend"
      >
        {{ isSending ? '发送中...' : '发送' }}
      </button>
      <span class="input-hint">Enter 发送，Shift + Enter 换行</span>
    </div>
  </section>
</template>
