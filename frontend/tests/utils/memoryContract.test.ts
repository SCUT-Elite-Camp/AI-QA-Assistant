import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { compactionPlanResponseSchema, internalChatRequestSchema, internalChatResponseSchema, memoryContextInputSchema } from '../../server/utils/memoryContract'

function readFixture (name: string): unknown {
  return JSON.parse(readFileSync(new URL(`../../../docs/memory-context-plan/evidence/fixtures/${name}`, import.meta.url), 'utf8'))
}

function createMemoryContext() {
  return {
    actor: {
      user_id: 'user-a',
      authenticated: true
    },
    chat_id: 'chat-a',
    revision: 2,
    current_message_id: 'message-3',
    current_sequence: 3,
    snapshot: {
      id: 'snapshot-1',
      version: 1,
      revision: 2,
      covered_to_sequence: 1,
      summary: 'A persisted summary.'
    },
    tail: [{
      id: 'message-2',
      sequence: 2,
      revision: 2,
      role: 'assistant',
      content: 'Previous response.'
    }]
  }
}

describe('internal Memory contract', () => {
  it('accepts the shared cross-workspace request and response fixtures', () => {
    expect(internalChatRequestSchema.parse(readFixture('internal-chat-request.json'))).toMatchObject({
      memory_context: { chat_id: 'chat-fixture-1', current_sequence: 3 }
    })
    expect(internalChatResponseSchema.parse(readFixture('internal-chat-response.json'))).toMatchObject({
      memory_decision: {},
      response: { trace_id: 'trace-fixture-1' }
    })
  })

  it('serializes the authenticated Memory context with Snapshot and Tail', () => {
    const parsed = internalChatRequestSchema.parse({
      query: 'Continue the previous topic.',
      memory_context: createMemoryContext()
    })

    expect(parsed.memory_context).toEqual(createMemoryContext())
  })

  it('rejects unknown fields, unauthenticated actors, and inconsistent Tail data', () => {
    const unknown = createMemoryContext() as Record<string, unknown>
    unknown.untrusted_user_id = 'user-b'
    expect(() => memoryContextInputSchema.parse(unknown)).toThrow()

    const invalidActor = createMemoryContext()
    invalidActor.actor.authenticated = false
    expect(() => memoryContextInputSchema.parse(invalidActor)).toThrow()

    const invalidTail = createMemoryContext()
    invalidTail.tail[0]!.sequence = invalidTail.current_sequence
    expect(() => memoryContextInputSchema.parse(invalidTail)).toThrow()

    const coveredTail = createMemoryContext()
    coveredTail.tail[0]!.sequence = coveredTail.snapshot!.covered_to_sequence
    expect(() => memoryContextInputSchema.parse(coveredTail)).toThrow()
  })

  it('keeps MemoryDecision inside the internal response envelope', () => {
    const parsed = internalChatResponseSchema.parse({
      response: {
        trace_id: 'trace-1',
        status: 'success',
        answer: 'Answer.',
        message: '',
        citations: []
      },
      memory_decision: {}
    })

    expect(parsed.response).not.toHaveProperty('memory_decision')
  })

  it('rejects retired Fact input and decision fields', () => {
    expect(() => memoryContextInputSchema.parse({ ...createMemoryContext(), facts: [] })).toThrow()
    const response = { trace_id: 'trace-1', status: 'success', answer: 'Answer.', message: '', citations: [] }
    expect(() => internalChatResponseSchema.parse({ response, memory_decision: { fact_proposals: [] } })).toThrow()
    expect(() => internalChatResponseSchema.parse({ response, memory_decision: { recall: { handled: true } } })).toThrow()
  })

  it('accepts only the two fixed compaction response shapes', () => {
    expect(compactionPlanResponseSchema.parse({ should_compact: false })).toEqual({
      should_compact: false
    })
    expect(compactionPlanResponseSchema.parse({
      should_compact: true,
      expected_active_snapshot: { id: 'snapshot-1', version: 1, revision: 2 },
      new_snapshot: {
        covered_from_sequence: 1,
        covered_to_sequence: 12,
        covered_from_message_id: 'message-1',
        covered_to_message_id: 'message-12',
        summary: 'Compacted history.'
      }
    })).toMatchObject({ should_compact: true })
    expect(() => compactionPlanResponseSchema.parse({
      should_compact: true,
      expected_active_snapshot: null
    })).toThrow()
  })
})
