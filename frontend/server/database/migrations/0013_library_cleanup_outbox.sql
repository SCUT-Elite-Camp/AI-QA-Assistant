CREATE TABLE `library_cleanup_jobs` (
  `id` text PRIMARY KEY NOT NULL,
  `action` text NOT NULL,
  `document_id` text NOT NULL,
  `version_id` text,
  `remote_object_id` text NOT NULL,
  `owner_user_id` text NOT NULL,
  `knowledge_base_id` text NOT NULL,
  `idempotency_key` text NOT NULL,
  `status` text DEFAULT 'pending' NOT NULL,
  `attempt_count` integer DEFAULT 0 NOT NULL,
  `max_attempts` integer DEFAULT 10 NOT NULL,
  `next_attempt_at` integer NOT NULL,
  `claim_token` text,
  `claimed_at` integer,
  `lease_expires_at` integer,
  `last_error_code` text DEFAULT '' NOT NULL,
  `last_error_message` text DEFAULT '' NOT NULL,
  `created_at` integer NOT NULL,
  `updated_at` integer NOT NULL,
  `completed_at` integer
);
--> statement-breakpoint
CREATE UNIQUE INDEX `library_cleanup_jobs_idempotency_idx`
ON `library_cleanup_jobs` (`idempotency_key`);
--> statement-breakpoint
CREATE INDEX `library_cleanup_jobs_claim_idx`
ON `library_cleanup_jobs` (`status`,`next_attempt_at`,`lease_expires_at`);
--> statement-breakpoint
CREATE INDEX `library_cleanup_jobs_document_idx`
ON `library_cleanup_jobs` (`document_id`);
