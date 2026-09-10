import fs from 'fs'
import path from 'path'
import { execSync } from 'child_process'
import { defineHandler, HTTPError } from 'nitro'
import { readBody } from 'h3'

export default defineHandler(async (event) => {
  const body = await readBody(event)
  const docIds: string[] = body?.docIds || (body?.docId ? [body.docId] : [])

  if (!docIds || !docIds.length) {
    throw new HTTPError({ statusCode: 400, statusMessage: 'No docIds provided for deletion' })
  }

  const docDir = path.resolve(process.cwd(), '../data-persistence/data/documents')
  const rawsDir = path.resolve(process.cwd(), '../data-persistence/data/raws')
  const projectRoot = path.resolve(process.cwd(), '..')

  let deletedCount = 0

  for (const docId of docIds) {
    // 1. Delete JSON document
    const jsonPath = path.join(docDir, `${docId}.json`)
    if (fs.existsSync(jsonPath)) {
      try {
        fs.unlinkSync(jsonPath)
        deletedCount++
      } catch (e) {
        console.warn(`[delete.post] Failed to unlink ${jsonPath}:`, e)
      }
    }

    // 2. Delete matching files in raws
    if (fs.existsSync(rawsDir)) {
      const files = fs.readdirSync(rawsDir)
      for (const f of files) {
        if (f.includes(docId) || docId.includes(f)) {
          try {
            fs.unlinkSync(path.join(rawsDir, f))
          } catch {}
        }
      }
    }
  }

  // 3. Trigger Python script to purge vector entities from Milvus & rebuild BM25
  try {
    const pythonExe = path.join(projectRoot, '.venv', 'Scripts', 'python.exe')
    const pyScript = `
import os, sys, json
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
sys.path.insert(0, r"${projectRoot}")
sys.path.insert(0, r"${path.join(projectRoot, 'data-persistence')}")
sys.path.insert(0, r"${path.join(projectRoot, 'data-pipeline')}")
from storage.milvus_store import MilvusStore
from retrieval.bm25_index import BM25Index

milvus = MilvusStore()
try:
    milvus.connect()
    milvus.init_collection('doc_chunks', dim=384)
    ids_str = ", ".join([f"'{d}'" for d in ${JSON.stringify(docIds)}])
    milvus.collection.delete(expr=f"doc_id in [{ids_str}]")
    milvus.collection.flush()
except Exception as e:
    print("Milvus purge warn:", e)

bm25 = BM25Index()
bm25.build_from_documents()
bm25.save(BM25Index.default_index_path())
`
    const pyPath = path.join(projectRoot, 'temp_delete_docs.py')
    fs.writeFileSync(pyPath, pyScript, 'utf-8')
    execSync(`"${pythonExe}" "${pyPath}"`, { cwd: projectRoot, timeout: 15000 })
    if (fs.existsSync(pyPath)) fs.unlinkSync(pyPath)
  } catch (err: any) {
    console.warn('[delete.post] Python Milvus/BM25 sync warn:', err?.message)
  }

  return {
    success: true,
    deletedCount,
    message: `Successfully deleted ${docIds.length} document(s)`
  }
})
