<script setup>
import ChatInput from './components/ChatInput.vue';
import ChatWindow from './components/ChatWindow.vue';
import { useChat } from './composables/useChat.js';

const {
  messages,
  input,
  isSending,
  inputError,
  canSend,
  sendMessage,
  clearMessages,
  copyMessage,
} = useChat();
</script>

<template>
  <main class="app-shell">
    <header class="app-header">
      <div>
        <p class="eyebrow">Web Layer MVP</p>
        <h1>AI 智能问答助手 Demo</h1>
        <p class="demo-note">当前为 Web Layer Mock Demo，后续将接入 Agent Layer</p>
      </div>
      <button class="secondary-button" type="button" @click="clearMessages">
        清空对话
      </button>
    </header>

    <section class="chat-panel" aria-label="聊天演示面板">
      <div class="panel-header">
        <div>
          <h2>聊天工作区</h2>
          <p>用户提问、Agent 回答、trace_id 和 citations 将在这里汇总展示。</p>
        </div>
        <span class="state-badge">{{ messages.length }} 条消息</span>
      </div>

      <ChatWindow
        :messages="messages"
        :is-sending="isSending"
        @copy="copyMessage"
      />

      <ChatInput
        v-model="input"
        :is-sending="isSending"
        :can-send="canSend"
        :input-error="inputError"
        @send="sendMessage"
      />
    </section>
  </main>
</template>
