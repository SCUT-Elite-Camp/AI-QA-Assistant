import fs from 'fs'
import os from 'os'
import path from 'path'
import { execFileSync } from 'child_process'
import { defineHandler, HTTPError } from 'nitro'
import { readBody } from 'nitro/h3'

const MAX_DOC_IDS = 500

function parseDocIds(body: any): string[] {
  const suppliedIds: unknown = body?.docIds ?? (body?.docId ? [body.docId] : [])
  if (!Array.isArray(suppliedIds) || suppliedIds.length === 0) {
    throw new HTTPError({ statusCode: 400, statusMessage: 'No docIds provided for deletion' })
  }
  if (suppliedIds.length > MAX_DOC_IDS) {
    throw new HTTPError({ statusCode: 400, statusMessage: `At most ${MAX_DOC_IDS} docIds may be deleted at once` })
  }

  const docIds = new Set<string>()
  for (const value of suppliedIds) {
    if (
      typeof value !== 'string'
      || value.length === 0
      || value.length > 128
      || value === '.'
      || value === '..'
      || /[\\/\0:]/.test(value)
    ) {
      throw new HTTPError({ statusCode: 400, statusMessage: 'Invalid document ID' })
    }
    docIds.add(value)
  }

  return [...docIds]
}

export default defineHandler(async (event) => {
  const body = await readBody(event)
  const docIds = parseDocIds(body)
  const projectRoot = path.resolve(process.cwd(), '..')
  const pythonExe = path.join(projectRoot, '.venv', 'Scripts', 'python.exe')
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ai-qa-delete-documents-'))
  const scriptPath = path.join(tempDir, 'delete_documents.py')

  const pythonScript = `
import json
import sys
from pathlib import Path

project_root = ${JSON.stringify(projectRoot)}
for dependency in (
    project_root,
    str(Path(project_root) / "data-persistence"),
    str(Path(project_root) / "data-pipeline"),
    str(Path(project_root) / "toolset"),
):
    if dependency not in sys.path:
        sys.path.insert(0, dependency)

from data_persistence.documents import delete_document, list_documents, load_document, resolve_documents_dir

doc_ids = json.load(sys.stdin)
documents = {}
for doc_id in doc_ids:
    try:
        documents[doc_id] = load_document(doc_id)
    except json.JSONDecodeError:
        # A corrupt metadata file can still be safely deleted by its validated ID.
        documents[doc_id] = None

existing_ids = set(list_documents())
deleted_count = 0
eligible_ids = []
failures = []
for doc_id in doc_ids:
    try:
        delete_document(doc_id)
    except Exception as exc:
        print(f"Document metadata deletion failed for {doc_id}: {exc}", file=sys.stderr)
        failures.append(doc_id)
        continue
    if doc_id in existing_ids:
        deleted_count += 1
    eligible_ids.append(doc_id)

warnings = []
documents_dir = Path(resolve_documents_dir())
raws_dir = documents_dir.parent / "raws"

def unlink_raw_file(address, doc_id):
    if not isinstance(address, str) or not address:
        warnings.append(f"Raw-source cleanup could not be determined for {doc_id}")
        return
    candidate = Path(address)
    if not candidate.is_absolute():
        warnings.append(f"Raw-source cleanup skipped for {doc_id}: invalid source path")
        return
    try:
        raw_root = raws_dir.resolve(strict=True)
    except FileNotFoundError:
        return
    except (OSError, RuntimeError) as exc:
        print(f"Raw-source root could not be resolved for {doc_id}: {exc}", file=sys.stderr)
        warnings.append(f"Raw-source cleanup failed for {doc_id}")
        return

    for label, raw_path in (
        ("source", candidate),
        ("sidecar", Path(str(candidate) + ".meta.json")),
    ):
        try:
            resolved = raw_path.resolve(strict=True)
        except FileNotFoundError:
            continue
        except (OSError, RuntimeError) as exc:
            print(f"Raw {label} could not be resolved for {doc_id}: {exc}", file=sys.stderr)
            warnings.append(f"Raw {label} cleanup failed for {doc_id}")
            continue
        if resolved == raw_root or raw_root not in resolved.parents:
            warnings.append(f"Raw {label} path outside raw storage for {doc_id}")
            continue
        if raw_path.is_symlink() or not resolved.is_file():
            warnings.append(f"Raw {label} is not a regular in-root file for {doc_id}")
            continue
        try:
            resolved.unlink()
        except OSError as exc:
            print(f"Raw {label} deletion failed for {doc_id}: {exc}", file=sys.stderr)
            warnings.append(f"Raw {label} deletion failed for {doc_id}")

for doc_id in eligible_ids:
    document = documents.get(doc_id)
    if doc_id in existing_ids:
        if not isinstance(document, dict):
            warnings.append(f"Raw-source cleanup could not be determined for {doc_id}")
        else:
            unlink_raw_file(document.get("address"), doc_id)

try:
    from data_persistence.vector import MilvusStore
    milvus = MilvusStore()
    milvus.delete_documents_chunks(eligible_ids)
except Exception as exc:
    print(f"Milvus purge failed: {exc}", file=sys.stderr)
    warnings.append("Milvus purge failed")

try:
    from retrieval.bm25_index import BM25Index
    # Keep stdout reserved for the machine-readable result consumed by Node.
    import contextlib
    with contextlib.redirect_stdout(sys.stderr):
        bm25 = BM25Index()
        bm25.build_from_documents()
        bm25.save(BM25Index.default_index_path())
except Exception as exc:
    print(f"BM25 rebuild failed: {exc}", file=sys.stderr)
    warnings.append("BM25 rebuild failed")

print(json.dumps({
    "deletedCount": deleted_count,
    "failures": failures,
    "warnings": warnings,
}, ensure_ascii=False))
`

  try {
    fs.writeFileSync(scriptPath, pythonScript, { encoding: 'utf8', mode: 0o600 })
    const output = execFileSync(pythonExe, [scriptPath], {
      cwd: projectRoot,
      input: JSON.stringify(docIds),
      encoding: 'utf8',
      timeout: 15000
    })
    const result = JSON.parse(output) as { deletedCount?: number, failures?: string[], warnings?: string[] }
    const failures = result.failures || []
    const warnings = result.warnings || []
    for (const warning of warnings) {
      console.warn('[delete.post] Persistence sync warn:', warning)
    }

    return {
      success: failures.length === 0 && warnings.length === 0,
      deletedCount: Number(result.deletedCount) || 0,
      failures,
      warnings,
      message: failures.length || warnings.length
        ? 'Deletion completed with errors'
        : `Successfully deleted ${docIds.length} document(s)`
    }
  } catch (error: any) {
    console.warn('[delete.post] Document deletion failed:', error?.message)
    throw new HTTPError({ statusCode: 500, statusMessage: 'Failed to delete documents' })
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true })
  }
})
