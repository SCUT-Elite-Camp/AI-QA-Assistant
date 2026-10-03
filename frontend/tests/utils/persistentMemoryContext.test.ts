import { describe, expect, it } from 'vitest'
import { createPersistentMemoryContext } from '../../server/utils/persistentMemoryContext'

describe('persistent Memory BFF context', () => {
  it('uses server-owned identity, revision, visible records, and excludes the current query from Tail', () => {
    const context = createPersistentMemoryContext(
      {
        actorUserId: 'user-a',
        chatId: 'chat-a',
        currentMessageId: 'message-3',
        currentSequence: 3,
        historyRevision: 2
      },
      {
        id: 'snapshot-1',
        chatId: 'chat-a',
        historyRevision: 2,
        version: 1,
        coveredFromSequence: 1,
        coveredToSequence: 1,
        coveredFromMessageId: 'message-1',
        coveredToMessageId: 'message-1',
        summary: 'Earlier history.',
        status: 'ACTIVE',
        archivedAt: null,
        createdAt: new Date()
      },
      [{
        id: 'fact-1',
        chatId: 'chat-a',
        historyRevision: 2,
        category: 'PREFERENCE',
        value: 'Use concise Chinese.',
        scope: 'SESSION',
        status: 'CONFIRMED',
        proposalKey: 'key',
        sourceMessageId: 'message-1',
        expiresAt: null,
        confirmedAt: new Date(),
        revokedAt: null,
        createdAt: new Date()
      }],
      [{
        id: 'message-2',
        historyRevision: 2,
        sequence: 2,
        role: 'assistant',
        parts: [{ type: 'text', text: 'Previous response.' }],
        createdAt: new Date()
      }, {
        id: 'message-3',
        historyRevision: 2,
        sequence: 3,
        role: 'user',
        parts: [{ type: 'text', text: 'Current query.' }],
        createdAt: new Date()
      }]
    )

    expect(context.actor).toEqual({ user_id: 'user-a', authenticated: true })
    expect(context.snapshot?.covered_to_sequence).toBe(1)
    expect(context.tail).toEqual([{
      id: 'message-2', sequence: 2, revision: 2, role: 'assistant', content: 'Previous response.'
    }])
  })
})
