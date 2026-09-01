CREATE TABLE `memory_facts` (
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
	FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`chat_id`) REFERENCES `chats`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`source_message_id`) REFERENCES `messages`(`id`) ON UPDATE no action ON DELETE set null,
	CONSTRAINT "memory_facts_category_check" CHECK("memory_facts"."category" IN ('GOAL', 'PREFERENCE', 'PLAN_CONSTRAINT')),
	CONSTRAINT "memory_facts_scope_check" CHECK("memory_facts"."scope" = 'SESSION'),
	CONSTRAINT "memory_facts_status_check" CHECK("memory_facts"."status" IN ('PROPOSED', 'CONFIRMED', 'REVOKED'))
);
--> statement-breakpoint
CREATE INDEX `memory_facts_user_chat_revision_status_expires_idx` ON `memory_facts` (`user_id`,`chat_id`,`history_revision`,`status`,`expires_at`);--> statement-breakpoint
CREATE UNIQUE INDEX `memory_facts_chat_revision_proposal_key_idx` ON `memory_facts` (`chat_id`,`history_revision`,`proposal_key`);--> statement-breakpoint
CREATE TABLE `memory_snapshots` (
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
	FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`chat_id`) REFERENCES `chats`(`id`) ON UPDATE no action ON DELETE cascade,
	CONSTRAINT "memory_snapshots_status_check" CHECK("memory_snapshots"."status" IN ('ACTIVE', 'ARCHIVED'))
);
--> statement-breakpoint
CREATE UNIQUE INDEX `memory_snapshots_chat_revision_version_idx` ON `memory_snapshots` (`chat_id`,`history_revision`,`version`);--> statement-breakpoint
CREATE INDEX `memory_snapshots_chat_revision_status_covered_to_idx` ON `memory_snapshots` (`chat_id`,`history_revision`,`status`,`covered_to_sequence`);