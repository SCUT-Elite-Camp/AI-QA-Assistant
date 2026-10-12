const messages: Record<string, string> = {
  attachments_unavailable: 'Attachment service is unavailable. Retry when it is running.',
  attachment_service_error: 'The attachment service could not process this file. Please retry.',
  network_error: 'Connection interrupted. Please retry the upload.',
  upload_timeout: 'Upload timed out. Please retry.',
  file_too_large: 'This file exceeds the upload size limit.',
  unsupported_file_type: 'This file format is not supported.',
  magic_mismatch: 'The file contents do not match its format.',
  mime_mismatch: 'The file type does not match its format.',
  encrypted_document: 'Upload an unencrypted copy of this file.',
  macro_document: 'Upload a copy without macros or a text version.',
  invalid_office: 'This Office file could not be read. Upload a valid copy.',
  invalid_pdf: 'This PDF could not be read. Upload a valid copy.',
  invalid_image: 'This image could not be read. Upload a valid copy.',
  image_too_large: 'The image exceeds the pixel limit.',
  too_many_pages: 'The PDF exceeds the page limit.',
  parse_timeout: 'File parsing timed out. Retry or upload a smaller file.',
  parse_failed: 'The file could not be parsed. Retry or upload a text version.',
  status_unavailable: 'Processing status is temporarily unavailable. Please retry.',
  batch_limit_exceeded: 'Upload up to 10 files and 100 MB per message.',
  batch_expired: 'The upload session expired. Please retry.',
  batch_failed: 'Could not start the upload. Please retry.',
  upload_failed: 'The file could not be uploaded. Please retry.',
}

export function attachmentErrorCode(payload: any, fallback = 'upload_failed'): string {
  return payload?.data?.code || payload?.data?.detail?.code || payload?.detail?.code
    || payload?.statusMessage || (messages[payload?.message] ? payload.message : fallback)
}

export function attachmentErrorMessage(code: string): string {
  return messages[code] || 'The file could not be processed. Please retry or use another format.'
}
