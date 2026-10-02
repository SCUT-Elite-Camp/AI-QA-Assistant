ALTER TABLE `library_documents` ADD `desired_version_id` text;
--> statement-breakpoint
ALTER TABLE `library_documents` ADD `latest_version_number` integer DEFAULT 0 NOT NULL;
--> statement-breakpoint
ALTER TABLE `document_versions` ADD `version_number` integer DEFAULT 0 NOT NULL;
--> statement-breakpoint
WITH ranked AS (
  SELECT id, ROW_NUMBER() OVER (PARTITION BY document_id ORDER BY created_at, id) AS number
  FROM document_versions
)
UPDATE document_versions
SET version_number = (SELECT number FROM ranked WHERE ranked.id = document_versions.id);
--> statement-breakpoint
UPDATE library_documents
SET latest_version_number = COALESCE((
  SELECT MAX(version_number) FROM document_versions WHERE document_id = library_documents.id
), 0),
desired_version_id = active_version_id;
--> statement-breakpoint
CREATE UNIQUE INDEX `document_versions_number_idx` ON `document_versions` (`document_id`,`version_number`);
