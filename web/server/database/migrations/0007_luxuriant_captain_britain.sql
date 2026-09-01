PRAGMA foreign_keys=OFF;--> statement-breakpoint
CREATE TABLE `__new_memory_facts` (
	`id` text PRIMARY KEY NOT NULL,
	`user_id` text NOT NULL,
	`chat_id` text NOT NULL,
	`history_revision` integer NOT NULL,
	`source_message_id` text,
	`category` text NOT NULL,
	`scope` text NOT NULL,
	`status` text NOT NULL,
	`value` text NOT NULL,
	`proposal_key` text NOT NULL,
	`expires_at` integer,
	`confirmed_at` integer,
	`revoked_at` integer,
	`created_at` integer NOT NULL,
	FOREIGN KEY (`chat_id`) REFERENCES `chats`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`source_message_id`) REFERENCES `messages`(`id`) ON UPDATE no action ON DELETE set null,
	CONSTRAINT "memory_facts_category_check" CHECK("__new_memory_facts"."category" IN ('GOAL', 'PREFERENCE', 'PLAN_CONSTRAINT')),
	CONSTRAINT "memory_facts_scope_check" CHECK("__new_memory_facts"."scope" = 'SESSION'),
	CONSTRAINT "memory_facts_status_check" CHECK("__new_memory_facts"."status" IN ('PROPOSED', 'CONFIRMED', 'REVOKED'))
);
--> statement-breakpoint
INSERT INTO `__new_memory_facts`("id", "user_id", "chat_id", "history_revision", "source_message_id", "category", "scope", "status", "value", "proposal_key", "expires_at", "confirmed_at", "revoked_at", "created_at") SELECT "id", "user_id", "chat_id", "history_revision", "source_message_id", "category", "scope", "status", "value", "proposal_key", "expires_at", "confirmed_at", "revoked_at", "created_at" FROM `memory_facts`;--> statement-breakpoint
DROP TABLE `memory_facts`;--> statement-breakpoint
ALTER TABLE `__new_memory_facts` RENAME TO `memory_facts`;--> statement-breakpoint
PRAGMA foreign_keys=ON;--> statement-breakpoint
CREATE INDEX `memory_facts_user_chat_revision_status_expires_idx` ON `memory_facts` (`user_id`,`chat_id`,`history_revision`,`status`,`expires_at`);--> statement-breakpoint
CREATE UNIQUE INDEX `memory_facts_chat_revision_proposal_key_idx` ON `memory_facts` (`chat_id`,`history_revision`,`proposal_key`);--> statement-breakpoint
CREATE TABLE `__new_memory_snapshots` (
	`id` text PRIMARY KEY NOT NULL,
	`user_id` text NOT NULL,
	`chat_id` text NOT NULL,
	`history_revision` integer NOT NULL,
	`version` integer NOT NULL,
	`covered_from_sequence` integer NOT NULL,
	`covered_to_sequence` integer NOT NULL,
	`covered_from_message_id` text NOT NULL,
	`covered_to_message_id` text NOT NULL,
	`summary` text NOT NULL,
	`status` text NOT NULL,
	`archived_at` integer,
	`created_at` integer NOT NULL,
	FOREIGN KEY (`chat_id`) REFERENCES `chats`(`id`) ON UPDATE no action ON DELETE cascade,
	CONSTRAINT "memory_snapshots_status_check" CHECK("__new_memory_snapshots"."status" IN ('ACTIVE', 'ARCHIVED'))
);
--> statement-breakpoint
INSERT INTO `__new_memory_snapshots`("id", "user_id", "chat_id", "history_revision", "version", "covered_from_sequence", "covered_to_sequence", "covered_from_message_id", "covered_to_message_id", "summary", "status", "archived_at", "created_at") SELECT "id", "user_id", "chat_id", "history_revision", "version", "covered_from_sequence", "covered_to_sequence", "covered_from_message_id", "covered_to_message_id", "summary", "status", "archived_at", "created_at" FROM `memory_snapshots`;--> statement-breakpoint
DROP TABLE `memory_snapshots`;--> statement-breakpoint
ALTER TABLE `__new_memory_snapshots` RENAME TO `memory_snapshots`;--> statement-breakpoint
CREATE UNIQUE INDEX `memory_snapshots_chat_revision_version_idx` ON `memory_snapshots` (`chat_id`,`history_revision`,`version`);--> statement-breakpoint
CREATE INDEX `memory_snapshots_chat_revision_status_covered_to_idx` ON `memory_snapshots` (`chat_id`,`history_revision`,`status`,`covered_to_sequence`);