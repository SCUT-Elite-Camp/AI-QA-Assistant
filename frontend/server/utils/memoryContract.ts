import { z } from 'zod'
import { answerClaimSchema } from '../../shared/answerClaims'
import { sourceDependencySchema } from './evidenceContract'

const sourceMetadata = {
  source_dependencies: z.array(sourceDependencySchema).optional(),
  provenance_complete: z.boolean().optional(),
}

export const memoryMessageSchema = z.object({
  id: z.string().min(1),
  sequence: z.number().int().positive(),
  revision: z.number().int().positive(),
  role: z.enum(['user', 'assistant', 'system']),
  content: z.string(),
  ...sourceMetadata,
}).strict()

export const memorySnapshotInputSchema = z.object({
  id: z.string().min(1),
  version: z.number().int().positive(),
  revision: z.number().int().positive(),
  covered_to_sequence: z.number().int().positive(),
  summary: z.string(),
  ...sourceMetadata,
}).strict()

export const internalActorSchema = z.object({
  user_id: z.string().min(1),
  authenticated: z.literal(true)
}).strict()

export const memoryContextInputSchema = z.object({
  actor: internalActorSchema,
  chat_id: z.string().min(1),
  revision: z.number().int().positive(),
  current_message_id: z.string().min(1),
  current_sequence: z.number().int().positive(),
  snapshot: memorySnapshotInputSchema.nullable().default(null),
  tail: z.array(memoryMessageSchema),
  ...sourceMetadata,
}).strict().superRefine((context, issue) => {
  if (context.snapshot && context.snapshot.revision !== context.revision) {
    issue.addIssue({
      code: 'custom',
      message: 'snapshot.revision must equal memory_context.revision',
      path: ['snapshot', 'revision']
    })
  }

  if (context.snapshot && context.snapshot.covered_to_sequence >= context.current_sequence) {
    issue.addIssue({
      code: 'custom',
      message: 'snapshot.covered_to_sequence must precede current_sequence',
      path: ['snapshot', 'covered_to_sequence']
    })
  }

  let previousSequence = 0
  const messageIds = new Set<string>()
  for (const [index, message] of context.tail.entries()) {
    if (message.revision !== context.revision) {
      issue.addIssue({
        code: 'custom',
        message: 'tail message revision must equal memory_context.revision',
        path: ['tail', index, 'revision']
      })
    }
    if (message.sequence >= context.current_sequence) {
      issue.addIssue({
        code: 'custom',
        message: 'tail message sequence must precede current_sequence',
        path: ['tail', index, 'sequence']
      })
    }
    if (context.snapshot && message.sequence <= context.snapshot.covered_to_sequence) {
      issue.addIssue({
        code: 'custom',
        message: 'tail message sequence must follow snapshot.covered_to_sequence',
        path: ['tail', index, 'sequence']
      })
    }
    if (message.sequence <= previousSequence) {
      issue.addIssue({
        code: 'custom',
        message: 'tail messages must be strictly ordered by sequence',
        path: ['tail', index, 'sequence']
      })
    }
    if (message.id === context.current_message_id || messageIds.has(message.id)) {
      issue.addIssue({
        code: 'custom',
        message: 'tail must not duplicate the current or another message ID',
        path: ['tail', index, 'id']
      })
    }
    previousSequence = message.sequence
    messageIds.add(message.id)
  }
})

const publicAgentChatRequestSchema = z.object({
  query: z.string(),
  session_id: z.string().nullable().optional(),
  top_k: z.number().int().min(1).max(20).default(5),
  filters: z.record(z.string(), z.unknown()).nullable().optional(),
  stream: z.boolean().default(false),
  retrieval_mode: z.enum(['vector', 'bm25', 'hybrid']).default('hybrid'),
  topic_id: z.string().nullable().optional(),
  weight_mode: z.enum(['auto', 'fast', 'thinking']).nullable().optional(),
  topic_doc_ids: z.array(z.string()).nullable().optional(),
  topic_titles: z.array(z.string()).nullable().optional(),
  consecutive_no_new_docs_count: z.number().int().nonnegative().default(0),
  is_first_message: z.boolean().nullable().optional()
}).strict()

/**
 * Contract-only envelope for the future token-protected /api/internal/chat.
 * The public /api/chat request remains separate and never consumes this type.
 */
export const internalChatRequestSchema = publicAgentChatRequestSchema.extend({
  memory_context: memoryContextInputSchema
}).strict()

const citationSchema = z.object({
  citation_id: z.number().int(),
  title: z.string(),
  source_url: z.string().nullable().optional(),
  doc_id: z.string(),
  chunk_id: z.string(),
  score: z.number().nullable().optional(),
  snippet: z.string().nullable().optional()
}).strict()

export const publicChatResponseSchema = z.object({
  trace_id: z.string(),
  status: z.string(),
  answer: z.string(),
  message: z.string(),
  citations: z.array(citationSchema),
  answer_claims: z.array(answerClaimSchema).optional(),
  chat_title: z.string().nullable().optional()
}).strict()

export const contextArtifactSchema = z.object({
  memory_brief: z.string(),
  model_history: z.array(memoryMessageSchema),
  metadata: z.record(z.string(), z.unknown()).default({})
}).strict()

export const memoryDecisionSchema = z.object({
  context_artifact: contextArtifactSchema.nullable().optional(),
}).strict()

export const internalChatResponseSchema = z.object({
  response: publicChatResponseSchema,
  memory_decision: memoryDecisionSchema
}).strict()

export const compactionPlanRequestSchema = z.object({
  actor: internalActorSchema,
  chat_id: z.string().min(1),
  revision: z.number().int().positive(),
  active_snapshot: memorySnapshotInputSchema.nullable(),
  messages: z.array(memoryMessageSchema)
}).strict().superRefine((request, issue) => {
  if (request.active_snapshot && request.active_snapshot.revision !== request.revision) {
    issue.addIssue({
      code: 'custom',
      message: 'active_snapshot.revision must equal revision',
      path: ['active_snapshot', 'revision']
    })
  }
})

export const expectedActiveSnapshotSchema = z.object({
  id: z.string().min(1),
  version: z.number().int().positive(),
  revision: z.number().int().positive()
}).strict()

export const newMemorySnapshotSchema = z.object({
  ...sourceMetadata,
  covered_from_sequence: z.number().int().positive(),
  covered_to_sequence: z.number().int().positive(),
  covered_from_message_id: z.string().min(1),
  covered_to_message_id: z.string().min(1),
  summary: z.string()
}).strict().superRefine((snapshot, issue) => {
  if (snapshot.covered_from_sequence > snapshot.covered_to_sequence) {
    issue.addIssue({
      code: 'custom',
      message: 'covered_from_sequence must not exceed covered_to_sequence',
      path: ['covered_from_sequence']
    })
  }
})

export const compactionPlanResponseSchema = z.discriminatedUnion('should_compact', [
  z.object({
    should_compact: z.literal(false)
  }).strict(),
  z.object({
    should_compact: z.literal(true),
    expected_active_snapshot: expectedActiveSnapshotSchema.nullable(),
    new_snapshot: newMemorySnapshotSchema
  }).strict()
])

export const resetShortWindowRequestSchema = z.object({
  chat_id: z.string().min(1)
}).strict()

export const resetShortWindowResponseSchema = z.object({
  status: z.literal('ok')
}).strict()

export type InternalChatRequest = z.infer<typeof internalChatRequestSchema>
export type InternalChatResponse = z.infer<typeof internalChatResponseSchema>
export type MemoryContextInput = z.infer<typeof memoryContextInputSchema>
export type CompactionPlanRequest = z.infer<typeof compactionPlanRequestSchema>
export type CompactionPlanResponse = z.infer<typeof compactionPlanResponseSchema>
