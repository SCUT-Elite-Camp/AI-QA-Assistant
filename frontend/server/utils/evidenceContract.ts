import { z } from 'zod'

export const sourceDependencySchema = z.object({
  source_type: z.enum(['knowledge', 'attachment', 'personal']), doc_id: z.string().min(1).max(256),
  // Pydantic serializes absent optional fields as null. Normalize these to
  // undefined; source-specific guards still require every applicable field.
  attachment_id: z.string().nullish().transform(value => value ?? undefined),
  knowledge_base_id: z.string().nullish().transform(value => value ?? undefined),
  document_id: z.string().nullish().transform(value => value ?? undefined),
  version_id: z.string().nullish().transform(value => value ?? undefined),
  version: z.union([z.string(), z.number()]).nullish().transform(value => value ?? undefined),
  content_hash: z.string().nullish().transform(value => value ?? undefined),
}).passthrough()
export type SourceDependency = z.infer<typeof sourceDependencySchema>
export const evidenceProvenanceSchema = z.object({
  schema_version: z.literal('evidence.provenance.v1'), complete: z.boolean(),
  dependencies: z.array(sourceDependencySchema).max(500), trace_id: z.string().optional(),
}).passthrough()
export type EvidenceProvenance = z.infer<typeof evidenceProvenanceSchema>
