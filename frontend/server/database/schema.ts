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

// ==================== Tables ====================

export const users = sqliteTable('users', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  email: text('email').notNull(),
  name: text('name').notNull(),
  avatar: text('avatar').notNull(),
  username: text('username').notNull(),
  provider: text('provider', { enum: ['github', 'sso'] }).notNull(),
  providerId: text('provider_id').notNull(),
  role: text('role', { enum: ['admin', 'user'] }).notNull().default('user'),
  ssoId: text('sso_id'),
  disabled: integer('disabled', { mode: 'boolean' }).notNull().default(false),
  ...timestamps
}, table => [
  uniqueIndex('users_provider_id_idx').on(table.provider, table.providerId),
  uniqueIndex('users_sso_id_idx').on(table.ssoId)
])

export const knowledgeBases = sqliteTable('knowledge_bases', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  name: text('name').notNull().default('My Library'),
  scopeType: text('scope_type', { enum: ['personal', 'enterprise'] }).notNull(),
  ownerUserId: text('owner_user_id'),
  workspaceId: text('workspace_id'),
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().$defaultFn(() => new Date()),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().$defaultFn(() => new Date()),
  deletedAt: integer('deleted_at', { mode: 'timestamp' })
}, table => [
  index('knowledge_bases_owner_idx').on(table.ownerUserId, table.scopeType),
])

export const libraryDocuments = sqliteTable('library_documents', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  knowledgeBaseId: text('knowledge_base_id').notNull().references(() => knowledgeBases.id),
  ownerUserId: text('owner_user_id').notNull(),
  workspaceId: text('workspace_id'),
  sourceScope: text('source_scope', { enum: ['personal', 'enterprise'] }).notNull(),
  sourceType: text('source_type').notNull().default('upload'),
  filename: text('filename').notNull(),
  displayName: text('display_name').notNull(),
  mimeType: text('mime_type').notNull(),
  docType: text('doc_type').notNull(),
  activeVersionId: text('active_version_id'),
  desiredVersionId: text('desired_version_id'),
  latestVersionNumber: integer('latest_version_number').notNull().default(0),
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().$defaultFn(() => new Date()),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().$defaultFn(() => new Date()),
  deletedAt: integer('deleted_at', { mode: 'timestamp' })
}, table => [
  index('library_documents_owner_idx').on(table.ownerUserId, table.deletedAt),
  index('library_documents_kb_idx').on(table.knowledgeBaseId, table.deletedAt)
])

export const documentVersions = sqliteTable('document_versions', {
  id: text('id').primaryKey(),
  documentId: text('document_id').notNull().references(() => libraryDocuments.id),
  contentHash: text('content_hash').notNull(),
  storageRef: text('storage_ref').notNull(),
  fileSize: integer('file_size').notNull(),
  versionNumber: integer('version_number').notNull(),
  status: text('status', { enum: ['UPLOADED', 'PARSING', 'CHUNKING', 'EMBEDDING', 'INDEXING', 'READY', 'FAILED', 'REINDEXING'] }).notNull(),
  errorCode: text('error_code').notNull().default(''),
  errorMessage: text('error_message').notNull().default(''),
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().$defaultFn(() => new Date()),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().$defaultFn(() => new Date()),
  indexedAt: integer('indexed_at', { mode: 'timestamp' })
}, table => [
  index('document_versions_document_idx').on(table.documentId, table.createdAt),
  uniqueIndex('document_versions_number_idx').on(table.documentId, table.versionNumber),
  uniqueIndex('document_versions_identity_idx').on(table.documentId, table.contentHash)
])

export const libraryCleanupJobs = sqliteTable('library_cleanup_jobs', {
  id: text('id').primaryKey(),
  action: text('action', { enum: ['delete_version'] }).notNull(),
  documentId: text('document_id').notNull(),
  versionId: text('version_id'),
  remoteObjectId: text('remote_object_id').notNull(),
  ownerUserId: text('owner_user_id').notNull(),
  knowledgeBaseId: text('knowledge_base_id').notNull(),
  idempotencyKey: text('idempotency_key').notNull(),
  status: text('status', { enum: ['pending', 'processing', 'retry', 'completed', 'dead'] }).notNull().default('pending'),
  attemptCount: integer('attempt_count').notNull().default(0),
  maxAttempts: integer('max_attempts').notNull().default(10),
  nextAttemptAt: integer('next_attempt_at', { mode: 'timestamp' }).notNull().$defaultFn(() => new Date()),
  claimToken: text('claim_token'),
  claimedAt: integer('claimed_at', { mode: 'timestamp' }),
  leaseExpiresAt: integer('lease_expires_at', { mode: 'timestamp' }),
  lastErrorCode: text('last_error_code').notNull().default(''),
  lastErrorMessage: text('last_error_message').notNull().default(''),
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().$defaultFn(() => new Date()),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().$defaultFn(() => new Date()),
  completedAt: integer('completed_at', { mode: 'timestamp' }),
}, table => [
  uniqueIndex('library_cleanup_jobs_idempotency_idx').on(table.idempotencyKey),
  index('library_cleanup_jobs_claim_idx').on(table.status, table.nextAttemptAt, table.leaseExpiresAt),
  index('library_cleanup_jobs_document_idx').on(table.documentId),
])

export const topics = sqliteTable('topics', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  title: text('title').notNull(),
  mainChatId: text('main_chat_id').notNull(),
  soulContent: text('soul_content').notNull().default(''),
  description: text('description'),
  weightMode: text('weight_mode', { enum: ['thinking', 'auto', 'fast', 'deeper', 'wider'] }).notNull().default('thinking'),
  tags: text('tags', { mode: 'json' }),
  status: text('status', { enum: ['generating', 'ready'] }).notNull().default('ready'),
  consecutiveNoNewDocsCount: integer('consecutive_no_new_docs_count').notNull().default(0),
  ...timestamps
})

export const topicMembers = sqliteTable('topic_members', {
  topicId: text('topic_id').notNull().references(() => topics.id, { onDelete: 'cascade' }),
  userId: text('user_id').notNull(),
  role: text('role', { enum: ['owner', 'editor', 'viewer'] }).notNull(),
  ...timestamps
}, table => [
  primaryKey({ columns: [table.topicId, table.userId] }),
  index('topic_members_user_idx').on(table.userId)
])

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
  index('chats_user_id_idx').on(table.userId)
])

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
  isUserUploaded: integer('is_user_uploaded', { mode: 'boolean' }).notNull().default(false),
  ...timestamps
}, table => [
  index('topic_docs_topic_id_idx').on(table.topicId),
  uniqueIndex('topic_doc_idx').on(table.topicId, table.docId)
])

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

export const memorySnapshots = sqliteTable('memory_snapshots', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
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

export const memoryFacts = sqliteTable('memory_facts', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
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

export const attachmentBatches = sqliteTable('attachment_batches', {
  id: text('id').primaryKey(),
  ownerId: text('owner_id').notNull(),
  scope: text('scope', { enum: ['draft', 'chat', 'topic'] }).notNull(),
  chatId: text('chat_id').references(() => chats.id, { onDelete: 'cascade' }),
  topicId: text('topic_id').references(() => topics.id, { onDelete: 'cascade' }),
  fileCount: integer('file_count').notNull().default(0),
  totalBytes: integer('total_bytes').notNull().default(0),
  expiresAt: integer('expires_at', { mode: 'timestamp' }),
  ...timestamps
}, table => [index('attachment_batches_owner_idx').on(table.ownerId)])

export const attachments = sqliteTable('attachments', {
  id: text('id').primaryKey(),
  batchId: text('batch_id').notNull().references(() => attachmentBatches.id, { onDelete: 'cascade' }),
  ownerId: text('owner_id').notNull(),
  scope: text('scope', { enum: ['draft', 'chat', 'topic'] }).notNull(),
  chatId: text('chat_id').references(() => chats.id, { onDelete: 'set null' }),
  topicId: text('topic_id').references(() => topics.id, { onDelete: 'cascade' }),
  filename: text('filename').notNull(),
  mimeType: text('mime_type').notNull(),
  sizeBytes: integer('size_bytes').notNull(),
  sha256: text('sha256').notNull(),
  status: text('status', { enum: ['uploading', 'scanning', 'parsing', 'ready', 'needs_review', 'failed', 'quarantined', 'expired', 'deleted'] }).notNull(),
  visionStatus: text('vision_status', { enum: ['not_requested', 'queued', 'running', 'ready', 'failed'] }).notNull().default('not_requested'),
  evidenceVersion: integer('evidence_version').notNull().default(1),
  errorCode: text('error_code').notNull().default(''),
  expiresAt: integer('expires_at', { mode: 'timestamp' }),
  deletedAt: integer('deleted_at', { mode: 'timestamp' }),
  ...timestamps
}, table => [
  index('attachments_owner_idx').on(table.ownerId),
  index('attachments_topic_idx').on(table.topicId),
  index('attachments_expiry_idx').on(table.expiresAt)
])

export const messageAttachments = sqliteTable('message_attachments', {
  messageId: text('message_id').notNull().references(() => messages.id, { onDelete: 'cascade' }),
  attachmentId: text('attachment_id').notNull().references(() => attachments.id, { onDelete: 'cascade' }),
  evidenceVersion: integer('evidence_version').notNull(),
  ...timestamps
}, table => [
  primaryKey({ columns: [table.messageId, table.attachmentId] }),
  index('message_attachments_attachment_idx').on(table.attachmentId)
])

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

export const votes = sqliteTable('votes', {
  chatId: text('chat_id').notNull().references(() => chats.id, { onDelete: 'cascade' }),
  messageId: text('message_id').notNull().references(() => messages.id, { onDelete: 'cascade' }),
  isUpvoted: integer('is_upvoted', { mode: 'boolean' }).notNull()
}, table => [
  primaryKey({ columns: [table.chatId, table.messageId] })
])

// ==================== 用户设置 ====================

export const userSettings = sqliteTable('user_settings', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  userId: text('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  theme: text('theme', { enum: ['light', 'dark', 'system'] }).notNull().default('system'),
  primaryColor: text('primary_color').notNull().default('blue'),
  neutralColor: text('neutral_color').notNull().default('zinc'),
  language: text('language', { enum: ['zh-CN', 'en-US'] }).notNull().default('zh-CN'),
  notificationsEnabled: integer('notifications_enabled', { mode: 'boolean' }).notNull().default(true),
  autoSaveChats: integer('auto_save_chats', { mode: 'boolean' }).notNull().default(true),
  fontSize: text('font_size', { enum: ['small', 'medium', 'large'] }).notNull().default('medium'),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().$defaultFn(() => new Date()),
  ...timestamps
}, table => [
  uniqueIndex('user_settings_user_id_idx').on(table.userId)
])

// ==================== 文件管理 ====================

export const files = sqliteTable('files', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  userId: text('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  name: text('name').notNull(),
  originalName: text('original_name').notNull(),
  mimeType: text('mime_type').notNull(),
  size: integer('size').notNull(), // bytes
  storagePath: text('storage_path').notNull(),
  visibility: text('visibility', { enum: ['private', 'shared'] }).notNull().default('private'),
  docId: text('doc_id'),
  ...timestamps
}, table => [
  index('files_user_id_idx').on(table.userId),
  index('files_visibility_idx').on(table.visibility),
  uniqueIndex('files_doc_id_idx').on(table.docId)
])

// ==================== 部门与组织 ====================

export const departments = sqliteTable('departments', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  name: text('name').notNull().unique(),
  parentId: text('parent_id'),
  ...timestamps
}, table => [
  index('departments_parent_id_idx').on(table.parentId)
])

export const userDepartments = sqliteTable('user_departments', {
  userId: text('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  departmentId: text('department_id').notNull().references(() => departments.id, { onDelete: 'cascade' }),
}, table => [
  primaryKey({ columns: [table.userId, table.departmentId] }),
  index('user_departments_user_idx').on(table.userId),
  index('user_departments_dept_idx').on(table.departmentId)
])

// ==================== 文件权限（个人级 ACL） ====================

export const filePermissions = sqliteTable('file_permissions', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  fileId: text('file_id').notNull().references(() => files.id, { onDelete: 'cascade' }),
  grantType: text('grant_type', { enum: ['user', 'department', 'public'] }).notNull(),
  grantId: text('grant_id'), // userId 或 departmentId，public 时为 null
  ...timestamps
}, table => [
  index('file_permissions_file_idx').on(table.fileId),
  index('file_permissions_grant_idx').on(table.grantType, table.grantId)
])

// ==================== 审计日志 ====================

export const auditLogs = sqliteTable('audit_logs', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  userId: text('user_id'),
  action: text('action').notNull(), // e.g. 'file.view', 'file.download', 'file.delete'
  resourceType: text('resource_type').notNull(), // e.g. 'file', 'chat'
  resourceId: text('resource_id'),
  detail: text('detail', { mode: 'json' }), // JSON: extra context
  ip: text('ip'),
  userAgent: text('user_agent'),
  ...timestamps
}, table => [
  index('audit_logs_user_id_idx').on(table.userId),
  index('audit_logs_action_idx').on(table.action),
  index('audit_logs_created_at_idx').on(table.createdAt)
])

// ==================== Relations ====================

export const usersRelations = relations(users, ({ many }) => ({
  chats: many(chats),
  memoryFacts: many(memoryFacts),
  memorySnapshots: many(memorySnapshots)
}))

export const knowledgeBasesRelations = relations(knowledgeBases, ({ many }) => ({
  documents: many(libraryDocuments)
}))

export const libraryDocumentsRelations = relations(libraryDocuments, ({ one, many }) => ({
  knowledgeBase: one(knowledgeBases, { fields: [libraryDocuments.knowledgeBaseId], references: [knowledgeBases.id] }),
  versions: many(documentVersions)
}))

export const documentVersionsRelations = relations(documentVersions, ({ one }) => ({
  document: one(libraryDocuments, { fields: [documentVersions.documentId], references: [libraryDocuments.id] })
}))

export const topicsRelations = relations(topics, ({ many }) => ({
  chats: many(chats),
  departments: many(userDepartments),
  documents: many(topicDocuments),
  members: many(topicMembers),
  attachments: many(attachments)
}))

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

export const topicDocumentsRelations = relations(topicDocuments, ({ one }) => ({
  topic: one(topics, {
    fields: [topicDocuments.topicId],
    references: [topics.id]
  })
}))

export const messagesRelations = relations(messages, ({ one, many }) => ({
  chat: one(chats, {
    fields: [messages.chatId],
    references: [chats.id]
  }),
  feedbacks: many(messageFeedbacks),
  memoryFacts: many(memoryFacts),
  attachments: many(messageAttachments)
}))

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

export const userSettingsRelations = relations(userSettings, ({ one }) => ({
  user: one(users, {
    fields: [userSettings.userId],
    references: [users.id]
  })
}))

export const filesRelations = relations(files, ({ one }) => ({
  user: one(users, {
    fields: [files.userId],
    references: [users.id]
  })
}))

export const auditLogsRelations = relations(auditLogs, ({ one }) => ({
  user: one(users, {
    fields: [auditLogs.userId],
    references: [users.id]
  })
}))

export const departmentsRelations = relations(departments, ({ one, many }) => ({
  parent: one(departments, {
    fields: [departments.parentId],
    references: [departments.id],
    relationName: 'department_parent'
  }),
  children: many(departments, { relationName: 'department_parent' }),
  users: many(userDepartments)
}))

export const userDepartmentsRelations = relations(userDepartments, ({ one }) => ({
  user: one(users, {
    fields: [userDepartments.userId],
    references: [users.id]
  }),
  department: one(departments, {
    fields: [userDepartments.departmentId],
    references: [departments.id]
  })
}))

export const filePermissionsRelations = relations(filePermissions, ({ one }) => ({
  file: one(files, {
    fields: [filePermissions.fileId],
    references: [files.id]
  })
}))
