import { mockSendChatMessage, mockSendChatMessageStream } from './mockAgent.js';
import { getErrorMessage } from '../utils/errorMap.js';

const DEFAULT_RETRIEVAL_MODE = 'hybrid';
const DEFAULT_SESSION_ID = 'local-session-001';
const DEFAULT_AGENT_BASE_URL = 'http://localhost:8000';
const DEFAULT_AGENT_CHAT_PATH = '/api/chat';

export async function sendChatMessage(payload = {}) {
  const normalizedPayload = normalizePayload(payload, false);

  if (shouldUseMock()) {
    return mockSendChatMessage(normalizedPayload);
  }

  return sendRealChatMessage(normalizedPayload);
}

export async function sendChatMessageStream(payload = {}, onDelta, onDone, onError) {
  const normalizedPayload = normalizePayload(payload, true);

  if (shouldUseMock()) {
    return mockSendChatMessageStream(normalizedPayload, onDelta, onDone, onError);
  }

  try {
    const response = await sendRealChatMessage({
      ...normalizedPayload,
      stream: false,
    });

    if (response.answer) {
      onDelta?.(response.answer);
    }

    onDone?.(response);
    return response;
  } catch (error) {
    const streamError = createApiError(
      error.status || 'stream_error',
      error.message || getErrorMessage('stream_error'),
      error.trace_id,
    );
    onError?.(streamError);
    throw streamError;
  }
}

function shouldUseMock() {
  return getEnvValue('VITE_USE_MOCK') !== 'false';
}

function buildChatUrl() {
  const baseUrl = getEnvValue('VITE_AGENT_BASE_URL') || DEFAULT_AGENT_BASE_URL;
  const chatPath = getEnvValue('VITE_AGENT_CHAT_PATH') || DEFAULT_AGENT_CHAT_PATH;

  return `${baseUrl.replace(/\/$/, '')}/${chatPath.replace(/^\//, '')}`;
}

function normalizePayload(payload = {}, stream = false) {
  return {
    query: payload.query,
    retrieval_mode: payload.retrieval_mode || DEFAULT_RETRIEVAL_MODE,
    session_id: payload.session_id || DEFAULT_SESSION_ID,
    stream,
  };
}

async function sendRealChatMessage(normalizedPayload) {
  let response;

  try {
    response = await fetch(buildChatUrl(), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(normalizedPayload),
    });
  } catch (error) {
    throw createApiError('network_error', getErrorMessage('network_error'));
  }

  let data = null;

  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    const status = data?.status || (response.status >= 500 ? 'network_error' : 'unknown_error');
    throw createApiError(status, data?.message || getErrorMessage(status), data?.trace_id);
  }

  return normalizeResponse(data);
}

function normalizeResponse(response = {}) {
  const status = response.status || 'success';

  return {
    trace_id: response.trace_id || '',
    status,
    answer: response.answer || '',
    message: response.message || '',
    citations: Array.isArray(response.citations) ? response.citations : [],
  };
}

function createApiError(status = 'unknown_error', message, traceId = '') {
  const error = new Error(message || getErrorMessage(status));
  error.status = status;
  error.trace_id = traceId;
  return error;
}

function getEnvValue(key) {
  return import.meta.env?.[key];
}
