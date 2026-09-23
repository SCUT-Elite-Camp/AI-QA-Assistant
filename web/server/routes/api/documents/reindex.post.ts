import path from 'path'
import { execSync } from 'child_process'
import { defineHandler } from 'nitro'

export default defineHandler(async () => {
  const projectRoot = path.resolve(process.cwd(), '..')

  try {
    const pythonExe = path.join(projectRoot, '.venv', 'Scripts', 'python.exe')
    const autoProcessScript = path.join(projectRoot, 'data-pipeline', 'pipeline', 'auto_process.py')

    execSync(`"${pythonExe}" "${autoProcessScript}"`, {
      cwd: projectRoot,
      env: {
        ...process.env,
        PYTHONPATH: `${projectRoot};${path.join(projectRoot, 'data-persistence')};${path.join(projectRoot, 'data-pipeline')};${path.join(projectRoot, 'toolset')}`,
        HF_HUB_OFFLINE: '1',
        TRANSFORMERS_OFFLINE: '1'
      },
      timeout: 90000
    })

    return {
      success: true,
      message: 'Document store and vector indices successfully re-indexed and updated!'
    }
  } catch (err: any) {
    return {
      success: false,
      message: `Re-indexing failed or finished with warnings: ${err?.message}`
    }
  }
})
