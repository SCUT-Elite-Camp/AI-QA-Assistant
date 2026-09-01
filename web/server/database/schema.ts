import { sqliteTable, text, integer, index, uniqueIndex, primaryKey, check } from 'drizzle-orm/sqlite-core'
import { relations, sql } from 'drizzle-orm'

const timestamps = {
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().$defaultFn(() => new Date())
}

export const memorySnapshotStatuses = ['ACTIVE', 'ARCHIVED'] as const
export const memoryFactCategories = ['GOAL', 'PREFERENCE', 'PLAN_CONSTRAINT'] as const
export const memoryFactScopes = ['SESSION'] as const
export const memoryFactStatuses = ['PROPOSED', 'CONFIRMED', 'REVOKED'] as const

export type MemorySnapshotStatus = typeof memorySnapshotStatuses[number]
export type MemoryFactCategory = typeof memoryFactCategories[number]
export type MemoryFactScope = typeof memoryFactScopes[number]
export type MemoryFactStatus = typeof memoryFactStatuses[number]

export const users = sqliteTable('users', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  email: text('email').notNull(),
  name: text('name').notNull(),
  avatar: text('avatar').notNull(),
  username: text('username').notNull(),
  provider: text('provider', { enum: ['github'] }).notNull(),
  providerId: text('provider_id').notNull(),
  ...timestamps
}, table => [
  uniqueIndex('users_provider_id_idx').on(table.provider, table.providerId)
])

export const usersRelations = relations(users, ({ many }) => ({
  chats: many(chats),
  memoryFacts: many(memoryFacts),
  memorySnapshots: many(memorySnapshots)
}))

export const topics = sqliteTable('topics', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  title: text('title').notNull(),
  mainChatId: text('main_chat_id').notNull(),
  soulContent: text('soul_content').notNull().default(''),
  description: text('description'),
  weightMode: text('weight_mode', { enum: ['deeper', 'auto', 'wider'] }).notNull().default('auto'),
  tags: text('tags', { mode: 'json' }),
  status: text('status', { enum: ['generating', 'ready'] }).notNull().default('ready'),
  consecutiveNoNewDocsCount: integer('consecutive_no_new_docs_count').notNull().default(0),
  ...timestamps
})

export const topicsRelations = relations(topics, ({ many }) => ({
  chats: many(chats),
  documents: many(topicDocuments)
}))

export const chats = sqliteTable('chats', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  title: text('title'),
  userId: text('user_id').notNull(),
  visibility: text('visibility', { enum: ['public', 'private'] }).notNull().default('private'),
  historyRevision: integer('history_revision').notNull().default(1),
  nextMessageSequence: integer('next_message_sequence').notNull().default(1),
  topicId: text('topic_id').references(() => topics.id, { onDelete: 'set null' }),
  isBranch: integer('is_branch', { mode: 'boolean' }).notNull().default(false),
  parentChatId: text('parent_chat_id'),
  parentMessageId: text('parent_message_id'),
  ...timestamps
}, table => [
  index('chats_user_id_idx').on(table.userId),
  index('chats_topic_id_idx').on(table.topicId)
])

export const chatsRelations = relations(chats, ({ one, many }) => ({
  user: one(users, {
    fields: [chats.userId],
    references: [users.id]
  }),
  topic: one(topics, {
    fields: [chats.topicId],
    references: [topics.id]
  }),
  messages: many(messages),
  memoryFacts: many(memoryFacts),
  memorySnapshots: many(memorySnapshots)
}))

export const topicDocuments = sqliteTable('topic_documents', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  topicId: text('topic_id').notNull().references(() => topics.id, { onDelete: 'cascade' }),
  docId: text('doc_id').notNull(),
  title: text('title').notNull(),
  sourceUrl: text('source_url'),
  snippet: text('snippet'),
  recallCount: integer('recall_count').notNull().default(1),
  lastRecalledAt: integer('last_recalled_at', { mode: 'timestamp' }).notNull().$defaultFn(() => new Date()),
  score: integer('score'),
  isRemoved: integer('is_removed', { mode: 'boolean' }).notNull().default(false),
  ...timestamps
}, table => [
  index('topic_docs_topic_id_idx').on(table.topicId),
  uniqueIndex('topic_doc_idx').on(table.topicId, table.docId)
])

export const topicDocumentsRelations = relations(topicDocuments, ({ one }) => ({
  topic: one(topics, {
    fields: [topicDocuments.topicId],
    references: [topics.id]
  })
}))

export const messages = sqliteTable('messages', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  chatId: text('chat_id').notNull().references(() => chats.id, { onDelete: 'cascade' }),
  role: text('role', { enum: ['user', 'assistant', 'system'] }).notNull(),
  parts: text('parts', { mode: 'json' }),
  sequence: integer('sequence').notNull(),
  historyRevision: integer('history_revision').notNull().default(1),
  requestId: text('request_id'),
  isFavorite: integer('is_favorite', { mode: 'boolean' }).notNull().default(false),
  suggestionText: text('suggestion_text'),
  ...timestamps
}, table => [
  index('messages_chat_id_idx').on(table.chatId),
  uniqueIndex('messages_chat_sequence_idx').on(table.chatId, table.sequence),
  uniqueIndex('messages_chat_request_role_idx')
    .on(table.chatId, table.requestId, table.role)
    .where(sql`${table.requestId} IS NOT NULL`)
])

export const messagesRelations = relations(messages, ({ one, many }) => ({
  chat: one(chats, {
    fields: [messages.chatId],
    references: [chats.id]
  }),
  feedbacks: many(messageFeedbacks),
  memoryFacts: many(memoryFacts)
}))

export const memorySnapshots = sqliteTable('memory_snapshots', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  // Chat ownership is authenticated against the external provider ID. Unlike
  // the optional local users profile table, that provider ID is always present
  // on chats, so Memory must not require a matching local users row.
  userId: text('user_id').notNull(),
  chatId: text('chat_id').notNull().references(() => chats.id, { onDelete: 'cascade' }),
  historyRevision: integer('history_revision').notNull(),
  version: integer('version').notNull(),
  coveredFromSequence: integer('covered_from_sequence').notNull(),
  coveredToSequence: integer('covered_to_sequence').notNull(),
  coveredFromMessageId: text('covered_from_message_id').notNull(),
  coveredToMessageId: text('covered_to_message_id').notNull(),
  summary: text('summary').notNull(),
  status: text('status', { enum: memorySnapshotStatuses }).notNull(),
  archivedAt: integer('archived_at', { mode: 'timestamp' }),
  ...timestamps
}, table => [
  check('memory_snapshots_status_check', sql`${table.status} IN ('ACTIVE', 'ARCHIVED')`),
  uniqueIndex('memory_snapshots_chat_revision_version_idx')
    .on(table.chatId, table.historyRevision, table.version),
  uniqueIndex('memory_snapshots_one_active_per_chat_revision_idx')
    .on(table.chatId, table.historyRevision)
    .where(sql`${table.status} = 'ACTIVE'`),
  index('memory_snapshots_chat_revision_status_covered_to_idx')
    .on(table.chatId, table.historyRevision, table.status, table.coveredToSequence)
])

export const memorySnapshotsRelations = relations(memorySnapshots, ({ one }) => ({
  chat: one(chats, {
    fields: [memorySnapshots.chatId],
    references: [chats.id]
  }),
  user: one(users, {
    fields: [memorySnapshots.userId],
    references: [users.id]
  })
}))

export const memoryFacts = sqliteTable('memory_facts', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  // See memorySnapshots.userId: ownership is enforced by the owned chat query,
  // not by a local users-table foreign key.
  userId: text('user_id').notNull(),
  chatId: text('chat_id').notNull().references(() => chats.id, { onDelete: 'cascade' }),
  historyRevision: integer('history_revision').notNull(),
  sourceMessageId: text('source_message_id').references(() => messages.id, { onDelete: 'set null' }),
  category: text('category', { enum: memoryFactCategories }).notNull(),
  scope: text('scope', { enum: memoryFactScopes }).notNull(),
  status: text('status', { enum: memoryFactStatuses }).notNull(),
  value: text('value').notNull(),
  proposalKey: text('proposal_key').notNull(),
  expiresAt: integer('expires_at', { mode: 'timestamp' }),
  confirmedAt: integer('confirmed_at', { mode: 'timestamp' }),
  revokedAt: integer('revoked_at', { mode: 'timestamp' }),
  ...timestamps
}, table => [
  check('memory_facts_category_check', sql`${table.category} IN ('GOAL', 'PREFERENCE', 'PLAN_CONSTRAINT')`),
  check('memory_facts_scope_check', sql`${table.scope} = 'SESSION'`),
  check('memory_facts_status_check', sql`${table.status} IN ('PROPOSED', 'CONFIRMED', 'REVOKED')`),
  index('memory_facts_user_chat_revision_status_expires_idx')
    .on(table.userId, table.chatId, table.historyRevision, table.status, table.expiresAt),
  uniqueIndex('memory_facts_chat_revision_proposal_key_idx')
    .on(table.chatId, table.historyRevision, table.proposalKey)
])

export const memoryFactsRelations = relations(memoryFacts, ({ one }) => ({
  chat: one(chats, {
    fields: [memoryFacts.chatId],
    references: [chats.id]
  }),
  sourceMessage: one(messages, {
    fields: [memoryFacts.sourceMessageId],
    references: [messages.id]
  }),
  user: one(users, {
    fields: [memoryFacts.userId],
    references: [users.id]
  })
}))

export const messageFeedbacks = sqliteTable('message_feedbacks', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  chatId: text('chat_id').notNull().references(() => chats.id, { onDelete: 'cascade' }),
  messageId: text('message_id').notNull().references(() => messages.id, { onDelete: 'cascade' }),
  isFavorite: integer('is_favorite', { mode: 'boolean' }).notNull().default(false),
  suggestionText: text('suggestion_text'),
  ...timestamps
}, table => [
  index('msg_feedbacks_chat_id_idx').on(table.chatId),
  index('msg_feedbacks_msg_id_idx').on(table.messageId)
])

export const messageFeedbacksRelations = relations(messageFeedbacks, ({ one }) => ({
  chat: one(chats, {
    fields: [messageFeedbacks.chatId],
    references: [chats.id]
  }),
  message: one(messages, {
    fields: [messageFeedbacks.messageId],
    references: [messages.id]
  })
}))

export const votes = sqliteTable('votes', {
  chatId: text('chat_id').notNull().references(() => chats.id, { onDelete: 'cascade' }),
  messageId: text('message_id').notNull().references(() => messages.id, { onDelete: 'cascade' }),
  isUpvoted: integer('is_upvoted', { mode: 'boolean' }).notNull()
}, table => [
  primaryKey({ columns: [table.chatId, table.messageId] })
])

export const votesRelations = relations(votes, ({ one }) => ({
  chat: one(chats, {
    fields: [votes.chatId],
    references: [chats.id]
  }),
  message: one(messages, {
    fields: [votes.messageId],
    references: [messages.id]
  })
}))

