import { getErrorMessage } from '../utils/errorMap.js';

const MOCK_LATENCY_MS = 300;
const STREAM_CHUNK_DELAY_MS = 120;

const NORMAL_ANSWER =
  '这是 Mock Agent 返回的回答。Q1 Web Layer MVP 需要先打通用户输入、Mock Agent 调用、助手回答展示、trace_id 展示、citations 展示和异常提示。';

const STREAM_ANSWER =
  '这是 Mock Agent 的流式回答。前端会逐段接收内容并追加到助手消息中，等全部片段返回后再结束 loading 状态。';

export async function mockSendChatMessage(payload = {}) {
  const query = getQuery(payload);

  await delay(MOCK_LATENCY_MS);

  if (query.includes('网络异常')) {
    throw createMockError('network_error');
  }

  if (query.includes('超时')) {
    throw createMockError('timeout_error');
  }

  return createResponseForQuery(query);
}

export async function mockSendChatMessageStream(
  payload = {},
  onDelta,
  onDone,
  onError,
) {
  const query = getQuery(payload);

  try {
    if (query.includes('网络异常')) {
      await delay(MOCK_LATENCY_MS);
      throw createMockError('network_error');
    }

    if (query.includes('超时')) {
      await delay(MOCK_LATENCY_MS);
      throw createMockError('timeout_error');
    }

    if (query.includes('流式异常')) {
      await delay(STREAM_CHUNK_DELAY_MS);
      onDelta?.('正在生成回答，但流式连接发生异常。');
      await delay(STREAM_CHUNK_DELAY_MS);
      throw createMockError('stream_error');
    }

    const finalResponse = createResponseForQuery(query, {
      forceStreamAnswer: query.includes('流式'),
    });

    if (finalResponse.status === 'success') {
      const chunks = splitAnswer(finalResponse.answer);

      for (const chunk of chunks) {
        await delay(STREAM_CHUNK_DELAY_MS);
        onDelta?.(chunk);
      }
    } else {
      await delay(MOCK_LATENCY_MS);
    }

    onDone?.(finalResponse);
    return finalResponse;
  } catch (error) {
    onError?.(error);
    throw error;
  }
}

function createResponseForQuery(query, options = {}) {
  if (query.includes('无相关')) {
    return createBusinessErrorResponse('no_relevant_context');
  }

  if (query.includes('检索异常')) {
    return createBusinessErrorResponse('retrieval_error');
  }

  if (query.includes('模型异常')) {
    return createBusinessErrorResponse('llm_error');
  }

  const answer = options.forceStreamAnswer ? STREAM_ANSWER : NORMAL_ANSWER;

  return {
    trace_id: createTraceId(),
    status: 'success',
    answer,
    message: 'ok',
    citations: [
      createBaseCitation({
        source_url: query.includes('无链接') ? '' : 'https://example.com/doc',
      }),
    ],
  };
}

function createBusinessErrorResponse(status) {
  return {
    trace_id: createTraceId(),
    status,
    answer: '',
    message: getErrorMessage(status),
    citations: [],
  };
}

function createTraceId() {
  return `mock-trace-${Date.now().toString(36)}-${Math.random()
    .toString(16)
    .slice(2, 8)}`;
}

function createBaseCitation(overrides = {}) {
  return {
    citation_id: 1,
    title: 'Q1 Web Layer MVP 说明',
    source_url: 'https://example.com/doc',
    doc_id: 'web-layer-mvp',
    chunk_id: 'chunk-001',
    score: 0.92,
    snippet: 'Web Layer 负责用户输入、消息展示、Agent 连接和流式输出展示。',
    ...overrides,
  };
}

function createMockError(status, message = getErrorMessage(status)) {
  const error = new Error(message);
  error.status = status;
  error.trace_id = createTraceId();
  return error;
}

function getQuery(payload) {
  return String(payload?.query ?? '');
}

function delay(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function splitAnswer(answer) {
  const chunks = [];
  let buffer = '';

  for (const char of answer) {
    buffer += char;

    if (/[，。；：、\s]/u.test(char) || buffer.length >= 8) {
      chunks.push(buffer);
      buffer = '';
    }
  }

  if (buffer) {
    chunks.push(buffer);
  }

  return chunks;
}
