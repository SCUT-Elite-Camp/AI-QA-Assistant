UPDATE `library_documents`
SET
  `deleted_at` = unixepoch(),
  `active_version_id` = NULL,
  `desired_version_id` = NULL,
  `updated_at` = unixepoch()
WHERE
  `source_scope` = 'personal'
  AND `deleted_at` IS NULL
  AND NOT EXISTS (
    SELECT 1
    FROM `document_versions`
    WHERE `document_versions`.`document_id` = `library_documents`.`id`
  );
