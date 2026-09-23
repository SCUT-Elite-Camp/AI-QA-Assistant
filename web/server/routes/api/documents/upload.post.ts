import fs from 'fs'
import path from 'path'
import { execSync } from 'child_process'
import { defineHandler, HTTPError } from 'nitro'
import { readMultipartFormData } from 'h3'

export default defineHandler(async (event) => {
  const parts = await readMultipartFormData(event)
  if (!parts || !parts.length) {
    throw new HTTPError({ statusCode: 400, statusMessage: 'No file uploaded' })
  }

  const rawsDir = path.resolve(process.cwd(), '../data-persistence/data/raws')
  const projectRoot = path.resolve(process.cwd(), '..')
  if (!fs.existsSync(rawsDir)) {
    fs.mkdirSync(rawsDir, { recursive: true })
  }

  const uploadedFiles: string[] = []

  for (const part of parts) {
    if (part.filename && part.data) {
      const safeFilename = path.basename(part.filename)
      const savePath = path.join(rawsDir, safeFilename)
      fs.writeFileSync(savePath, part.data)
      uploadedFiles.push(safeFilename)
    }
  }

  if (!uploadedFiles.length) {
    throw new HTTPError({ statusCode: 400, statusMessage: 'No valid file attached' })
  }

  // Run Python targeted process_specific_files pipeline for ONLY uploaded file(s)
  try {
    const pythonExe = path.join(projectRoot, '.venv', 'Scripts', 'python.exe')
    const targetedScript = path.join(projectRoot, 'data-pipeline', 'pipeline', 'process_specific_files.py')
    
    const fileArgs = uploadedFiles.map(fn => `"${path.join(rawsDir, fn)}"`).join(' ')
    
    execSync(`"${pythonExe}" "${targetedScript}" ${fileArgs}`, {
      cwd: projectRoot,
      env: {
        ...process.env,
        PYTHONPATH: `${projectRoot};${path.join(projectRoot, 'data-persistence')};${path.join(projectRoot, 'data-pipeline')};${path.join(projectRoot, 'toolset')}`,
        HF_HUB_OFFLINE: '1',
        TRANSFORMERS_OFFLINE: '1'
      },
      timeout: 60000
    })
  } catch (err: any) {
    console.warn('[upload.post] Python targeted ingestion warn:', err?.message)
  }

  return {
    success: true,
    uploadedFiles,
    message: `Successfully uploaded and ingested ${uploadedFiles.length} file(s)`
  }
})
