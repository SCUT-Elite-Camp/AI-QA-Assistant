CREATE TABLE `knowledge_bases` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text DEFAULT 'My Library' NOT NULL,
	`scope_type` text NOT NULL,
	`owner_user_id` text,
	`workspace_id` text,
	`created_at` integer NOT NULL,
	`updated_at` integer NOT NULL,
	`deleted_at` integer,
	CHECK ((scope_type = 'personal' AND owner_user_id IS NOT NULL AND workspace_id IS NULL) OR (scope_type = 'enterprise' AND workspace_id IS NOT NULL))
);
--> statement-breakpoint
CREATE INDEX `knowledge_bases_owner_idx` ON `knowledge_bases` (`owner_user_id`,`scope_type`);
--> statement-breakpoint
CREATE TABLE `library_documents` (
	`id` text PRIMARY KEY NOT NULL,
	`knowledge_base_id` text NOT NULL REFERENCES knowledge_bases(id),
	`owner_user_id` text NOT NULL,
	`workspace_id` text,
	`source_scope` text NOT NULL,
	`source_type` text DEFAULT 'upload' NOT NULL,
	`filename` text NOT NULL,
	`display_name` text NOT NULL,
	`mime_type` text NOT NULL,
	`doc_type` text NOT NULL,
	`active_version_id` text,
	`created_at` integer NOT NULL,
	`updated_at` integer NOT NULL,
	`deleted_at` integer
);
--> statement-breakpoint
CREATE INDEX `library_documents_owner_idx` ON `library_documents` (`owner_user_id`,`deleted_at`);
--> statement-breakpoint
CREATE INDEX `library_documents_kb_idx` ON `library_documents` (`knowledge_base_id`,`deleted_at`);
--> statement-breakpoint
CREATE TABLE `document_versions` (
	`id` text PRIMARY KEY NOT NULL,
	`document_id` text NOT NULL REFERENCES library_documents(id),
	`content_hash` text NOT NULL,
	`storage_ref` text NOT NULL,
	`file_size` integer NOT NULL,
	`status` text NOT NULL,
	`error_code` text DEFAULT '' NOT NULL,
	`error_message` text DEFAULT '' NOT NULL,
	`created_at` integer NOT NULL,
	`updated_at` integer NOT NULL,
	`indexed_at` integer
);
--> statement-breakpoint
CREATE INDEX `document_versions_document_idx` ON `document_versions` (`document_id`,`created_at`);
--> statement-breakpoint
CREATE UNIQUE INDEX `document_versions_identity_idx` ON `document_versions` (`document_id`,`content_hash`);
