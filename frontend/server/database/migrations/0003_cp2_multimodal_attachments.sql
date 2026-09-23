CREATE TABLE `topic_members` (
  `topic_id` text NOT NULL REFERENCES `topics`(`id`) ON DELETE cascade,
  `user_id` text NOT NULL,
  `role` text NOT NULL CHECK (`role` IN ('owner', 'editor', 'viewer')),
  `created_at` integer NOT NULL,
  PRIMARY KEY (`topic_id`, `user_id`)
);
--> statement-breakpoint
CREATE INDEX `topic_members_user_idx` ON `topic_members` (`user_id`);
--> statement-breakpoint
INSERT OR IGNORE INTO `topic_members` (`topic_id`, `user_id`, `role`, `created_at`)
SELECT `topics`.`id`, `chats`.`user_id`, 'owner', unixepoch()
FROM `topics` JOIN `chats` ON `chats`.`id` = `topics`.`main_chat_id`;
--> statement-breakpoint
CREATE TABLE `attachment_batches` (
  `id` text PRIMARY KEY NOT NULL,
  `owner_id` text NOT NULL,
  `scope` text NOT NULL CHECK (`scope` IN ('draft', 'chat', 'topic')),
  `chat_id` text REFERENCES `chats`(`id`) ON DELETE cascade,
  `topic_id` text REFERENCES `topics`(`id`) ON DELETE cascade,
  `file_count` integer DEFAULT 0 NOT NULL,
  `total_bytes` integer DEFAULT 0 NOT NULL,
  `expires_at` integer,
  `created_at` integer NOT NULL
);
--> statement-breakpoint
CREATE INDEX `attachment_batches_owner_idx` ON `attachment_batches` (`owner_id`);
--> statement-breakpoint
CREATE TABLE `attachments` (
  `id` text PRIMARY KEY NOT NULL,
  `batch_id` text NOT NULL REFERENCES `attachment_batches`(`id`) ON DELETE cascade,
  `owner_id` text NOT NULL,
  `scope` text NOT NULL CHECK (`scope` IN ('draft', 'chat', 'topic')),
  `chat_id` text REFERENCES `chats`(`id`) ON DELETE set null,
  `topic_id` text REFERENCES `topics`(`id`) ON DELETE cascade,
  `filename` text NOT NULL,
  `mime_type` text NOT NULL,
  `size_bytes` integer NOT NULL,
  `sha256` text NOT NULL,
  `status` text NOT NULL,
  `vision_status` text DEFAULT 'not_requested' NOT NULL,
  `evidence_version` integer DEFAULT 1 NOT NULL,
  `error_code` text DEFAULT '' NOT NULL,
  `expires_at` integer,
  `deleted_at` integer,
  `created_at` integer NOT NULL
);
--> statement-breakpoint
CREATE INDEX `attachments_owner_idx` ON `attachments` (`owner_id`);
--> statement-breakpoint
CREATE INDEX `attachments_topic_idx` ON `attachments` (`topic_id`);
--> statement-breakpoint
CREATE INDEX `attachments_expiry_idx` ON `attachments` (`expires_at`);
--> statement-breakpoint
CREATE TABLE `message_attachments` (
  `message_id` text NOT NULL REFERENCES `messages`(`id`) ON DELETE cascade,
  `attachment_id` text NOT NULL REFERENCES `attachments`(`id`) ON DELETE cascade,
  `evidence_version` integer NOT NULL,
  `created_at` integer NOT NULL,
  PRIMARY KEY (`message_id`, `attachment_id`)
);
--> statement-breakpoint
CREATE INDEX `message_attachments_attachment_idx` ON `message_attachments` (`attachment_id`);
