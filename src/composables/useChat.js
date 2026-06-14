import { computed, ref } from 'vue';
import { sendChatMessage, sendChatMessageStream } from '../api/agentApi.js';
import { getErrorMessage } from '../utils/errorMap.js';

export function useChat() {
  const messages = ref([]);
  const input = ref('');
  const isSending = ref(false);
  const inputError = ref('');

  const canSend = computed(() => input.value.trim().length > 0 && !isSending.value);

  async function sendMessage() {
    const query = input.value.trim();

    if (!query) {
      inputError.value = getErrorMessage('invalid_query');
      return;
    }

    if (isSending.value) {
      return;
    }

    inputError.value = '';
    isSending.value = true;

    const userMessage = createUserMessage(query);
    const assistantMessage = createAssistantMessage({ loading: true });

    messages.value.push(userMessage, assistantMessage);
    input.value = '';

    try {
      if (query.includes('流式')) {
        await sendStreamingMessage(query, assistantMessage.id);
        return;
      }

      const response = await sendChatMessage({ query });
      applyAgentResponse(assistantMessage.id, response);
    } catch (error) {
      applyErrorResponse(assistantMessage.id, error);
    } finally {
      updateMessage(assistantMessage.id, { loading: false });
      isSending.value = false;
    }
  }

  async function sendStreamingMessage(query, assistantMessageId) {
    await sendChatMessageStream(
      { query },
      (chunk) => {
        const message = findMessage(assistantMessageId);
        const currentContent = message?.content || '';
        updateMessage(assistantMessageId, {
          content: `${currentContent}${chunk}`,
          status: 'loading',
          loading: true,
          error: false,
        });
      },
      (response) => {
        applyAgentResponse(assistantMessageId, response, { preserveContent: true });
      },
      (error) => {
        applyErrorResponse(assistantMessageId, error);
      },
    );
  }

  function clearMessages() {
    messages.value = [];
    inputError.value = '';
  }

  async function copyMessage(message) {
    if (!message || message.role !== 'assistant' || !message.content) {
      return false;
    }

    const clipboard = globalThis.navigator?.clipboard;

    if (!clipboard?.writeText) {
      return false;
    }

    try {
      await clipboard.writeText(message.content);
      return true;
    } catch {
      return false;
    }
  }

  function createUserMessage(content) {
    return createMessage({
      role: 'user',
      content,
      status: 'success',
    });
  }

  function createAssistantMessage(partialData = {}) {
    return createMessage({
      role: 'assistant',
      status: partialData.loading ? 'loading' : 'success',
      loading: false,
      ...partialData,
    });
  }

  function updateMessage(messageId, patch) {
    const index = messages.value.findIndex((message) => message.id === messageId);

    if (index === -1) {
      return null;
    }

    messages.value[index] = {
      ...messages.value[index],
      ...patch,
    };

    return messages.value[index];
  }

  function createMessage(partialData = {}) {
    return {
      id: createMessageId(),
      role: partialData.role || 'assistant',
      content: partialData.content || '',
      status: partialData.status || 'success',
      trace_id: partialData.trace_id || '',
      citations: normalizeCitations(partialData.citations),
      loading: Boolean(partialData.loading),
      error: Boolean(partialData.error),
      createdAt: partialData.createdAt || Date.now(),
    };
  }

  function applyAgentResponse(messageId, response = {}, options = {}) {
    if (isBusinessSuccess(response)) {
      const message = findMessage(messageId);
      const content = options.preserveContent && message?.content
        ? message.content
        : response.answer || '';

      updateMessage(messageId, {
        content,
        status: 'success',
        trace_id: response.trace_id || '',
        citations: normalizeCitations(response.citations),
        loading: false,
        error: false,
      });
      return;
    }

    updateMessage(messageId, {
      content: getErrorMessage(response.status, response.message),
      status: 'error',
      trace_id: response.trace_id || '',
      citations: normalizeCitations(response.citations),
      loading: false,
      error: true,
    });
  }

  function applyErrorResponse(messageId, error = {}) {
    updateMessage(messageId, {
      content: getErrorMessage(error.status, error.message),
      status: 'error',
      trace_id: error.trace_id || '',
      citations: [],
      loading: false,
      error: true,
    });
  }

  function findMessage(messageId) {
    return messages.value.find((message) => message.id === messageId);
  }

  return {
    messages,
    input,
    isSending,
    inputError,
    canSend,
    sendMessage,
    clearMessages,
    copyMessage,
    createUserMessage,
    createAssistantMessage,
    updateMessage,
  };
}

function createMessageId() {
  return `msg-${Date.now().toString(36)}-${Math.random().toString(16).slice(2, 8)}`;
}

function normalizeCitations(citations = []) {
  return Array.isArray(citations) ? citations : [];
}

function isBusinessSuccess(response = {}) {
  return (response.status || 'success') === 'success';
}
