import { z } from 'zod'

export const memoryFactCategorySchema = z.enum([
  'GOAL',
  'PREFERENCE',
  'PLAN_CONSTRAINT'
])

export const memoryMessageSchema = z.object({
  id: z.string().min(1),
  sequence: z.number().int().positive(),
  revision: z.number().int().positive(),
  role: z.enum(['user', 'assistant', 'system']),
  content: z.string()
}).strict()

export const memorySnapshotInputSchema = z.object({
  id: z.string().min(1),
  version: z.number().int().positive(),
  revision: z.number().int().positive(),
  covered_to_sequence: z.number().int().positive(),
  summary: z.string()
}).strict()

/** Unix epoch milliseconds in UTC, or null when the Fact does not expire. */
export const memoryExpiresAtSchema = z.number().int().nonnegative().nullable()

export const memoryFactInputSchema = z.object({
  id: z.string().min(1),
  category: memoryFactCategorySchema,
  value: z.string(),
  expires_at: memoryExpiresAtSchema
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
  facts: z.array(memoryFactInputSchema),
  tail: z.array(memoryMessageSchema)
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
  weight_mode: z.enum(['deeper', 'auto', 'wider']).nullable().optional(),
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
  chat_title: z.string().nullable().optional()
}).strict()

export const contextArtifactSchema = z.object({
  memory_brief: z.string(),
  model_history: z.array(memoryMessageSchema),
  metadata: z.record(z.string(), z.unknown()).default({})
}).strict()

export const factProposalSchema = z.object({
  category: memoryFactCategorySchema,
  value: z.string(),
  source_message_id: z.string().min(1),
  expires_at: memoryExpiresAtSchema
}).strict()

export const memoryRecallSchema = z.object({
  handled: z.boolean(),
  answer: z.string().nullable().optional()
}).strict()

export const memoryDecisionSchema = z.object({
  context_artifact: contextArtifactSchema.nullable().optional(),
  fact_proposals: z.array(factProposalSchema).default([]),
  recall: memoryRecallSchema.nullable().optional()
}).strict()

export const internalChatResponseSchema = z.object({
  response: publicChatResponseSchema,
  memory_decision: memoryDecisionSchema
}).strict()

export type InternalChatRequest = z.infer<typeof internalChatRequestSchema>
export type InternalChatResponse = z.infer<typeof internalChatResponseSchema>
export type MemoryContextInput = z.infer<typeof memoryContextInputSchema>
