import { app, BrowserWindow, ipcMain } from 'electron'
import { spawn } from 'child_process'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const PYTHON_BACKEND_BASE_URL = 'http://127.0.0.1:8000'
const BACKEND_HOST = '127.0.0.1'
const BACKEND_PORT = '8000'
const WORKSPACE_ROOT = path.resolve(__dirname, '..', '..')
const VENV_PYTHON_PATH = path.join(WORKSPACE_ROOT, '.venv', 'bin', 'python')

let mainWindow
let petUpdateTimer = null
let monitoringStateTimer = null
let pythonProcess = null
let backendManagedByElectron = false
let isQuitting = false

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function isBackendReachable() {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 1200)
  try {
    const response = await fetch(`${PYTHON_BACKEND_BASE_URL}/monitoring/state`, {
      signal: controller.signal,
    })
    return response.ok
  } catch {
    return false
  } finally {
    clearTimeout(timeout)
  }
}

async function waitForBackendReady(maxAttempts = 30, intervalMs = 250) {
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    if (await isBackendReachable()) {
      return true
    }
    await sleep(intervalMs)
  }
  return false
}

async function ensureBackendRunning() {
  if (await isBackendReachable()) {
    console.log('[Perch] Backend already running; lifecycle is externally managed.')
    return
  }

  if (!fs.existsSync(VENV_PYTHON_PATH)) {
    throw new Error(
      `[Perch] Cannot find virtualenv Python at ${VENV_PYTHON_PATH}. ` +
      'Create .venv and install backend dependencies first.'
    )
  }

  pythonProcess = spawn(
    VENV_PYTHON_PATH,
    ['-m', 'uvicorn', 'app.main:app', '--host', BACKEND_HOST, '--port', BACKEND_PORT],
    {
      cwd: WORKSPACE_ROOT,
      stdio: ['ignore', 'pipe', 'pipe'],
    }
  )
  backendManagedByElectron = true

  pythonProcess.stdout.on('data', (chunk) => {
    process.stdout.write(`[Perch:python] ${chunk}`)
  })

  pythonProcess.stderr.on('data', (chunk) => {
    process.stderr.write(`[Perch:python] ${chunk}`)
  })

  pythonProcess.on('exit', (code, signal) => {
    if (!isQuitting) {
      console.error(`[Perch] Managed Python backend exited unexpectedly (code=${code}, signal=${signal})`)
    }
  })

  const ready = await waitForBackendReady()
  if (!ready) {
    throw new Error('[Perch] Managed Python backend did not become ready in time.')
  }
}

async function stopManagedBackend() {
  if (!backendManagedByElectron || !pythonProcess) {
    return
  }

  const target = pythonProcess
  pythonProcess = null
  backendManagedByElectron = false

  await new Promise((resolve) => {
    let settled = false
    const resolveOnce = () => {
      if (!settled) {
        settled = true
        resolve()
      }
    }

    target.once('exit', () => {
      resolveOnce()
    })

    try {
      target.kill('SIGTERM')
    } catch {
      resolveOnce()
      return
    }

    setTimeout(() => {
      if (!settled) {
        try {
          target.kill('SIGKILL')
        } catch {
          // Ignore if already dead.
        }
      }
    }, 2500)

    setTimeout(() => {
      resolveOnce()
    }, 5000)
  })
}

async function apiGet(route) {
  const response = await fetch(`${PYTHON_BACKEND_BASE_URL}${route}`)
  if (!response.ok) {
    throw new Error(`GET ${route} failed: ${response.status}`)
  }
  return response.json()
}

async function apiPost(route, payload) {
  const response = await fetch(`${PYTHON_BACKEND_BASE_URL}${route}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(`POST ${route} failed: ${response.status}`)
  }
  return response.json()
}

async function apiGetMonitoringState() {
  return apiGet('/monitoring/state')
}

function mapLegacyProfilePayload(input = {}) {
  if ('username' in input) {
    return {
      username: input.username || '',
      gender: input.gender || 'prefer_not_to_say',
      freeTime: input.freeTime || input.free_time || '',
      reminders: input.reminders || {
        hydration: true,
        stretching: true,
        meetings: true,
      },
      onboarding_completed: input.onboarding_completed ?? true,
      created_at: input.created_at || new Date().toISOString(),
    }
  }

  return {
    username: input.name || '',
    gender: input.gender || 'prefer_not_to_say',
    freeTime: input.freeTime || '',
    reminders: input.reminders || {
      hydration: true,
      stretching: true,
      meetings: true,
    },
    onboarding_completed: true,
    created_at: new Date().toISOString(),
  }
}

function startPetUpdatePolling() {
  if (petUpdateTimer) {
    clearInterval(petUpdateTimer)
  }

  petUpdateTimer = setInterval(async () => {
    if (!mainWindow || mainWindow.isDestroyed()) {
      return
    }
    try {
      const pet = await apiGet('/pet/update')
      mainWindow.webContents.send('pet:update', pet)
    } catch (error) {
      // Keep polling even if backend is temporarily unavailable.
      console.error('[Perch] Failed to poll /pet/update', error)
    }
  }, 5000)
}

function startMonitoringStatePolling() {
  if (monitoringStateTimer) {
    clearInterval(monitoringStateTimer)
  }

  monitoringStateTimer = setInterval(async () => {
    if (!mainWindow || mainWindow.isDestroyed()) {
      return
    }
    try {
      const monitoringState = await apiGetMonitoringState()
      mainWindow.webContents.send('monitoring:state', monitoringState)
    } catch (error) {
      console.error('[Perch] Failed to poll /monitoring/state', error)
    }
  }, 5000)
}

function registerIpcHandlers() {
  ipcMain.handle('app:ready', async () => {
    const bundle = await apiGet('/config/load')
    const pet = await apiGet('/pet/update')
    const monitoringState = await apiGetMonitoringState()

    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('profile:loaded', bundle.profile)
      mainWindow.webContents.send('settings:loaded', bundle.settings)
      mainWindow.webContents.send('pet:update', pet)
      mainWindow.webContents.send('monitoring:state', monitoringState)
    }

    return { success: true }
  })

  ipcMain.handle('profile:save', async (_event, profile) => {
    const payload = mapLegacyProfilePayload(profile)
    return apiPost('/config/save-profile', payload)
  })

  ipcMain.handle('settings:save', async (_event, settings) => {
    return apiPost('/config/save-settings', settings)
  })

  ipcMain.handle('pet:interaction', async (_event, _data) => {
    const pet = await apiGet('/pet/update')
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('pet:update', pet)
    }
    return { success: true }
  })
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 420,
    height: 420,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true
    }
  })

  mainWindow.loadURL('http://localhost:5173')
  startPetUpdatePolling()
  startMonitoringStatePolling()
}

app.whenReady().then(() => {
  return ensureBackendRunning()
    .then(() => {
      registerIpcHandlers()
      createWindow()
    })
    .catch((error) => {
      console.error('[Perch] Failed to start app runtime', error)
      app.quit()
    })
})

app.on('before-quit', (event) => {
  if (isQuitting) {
    return
  }

  isQuitting = true
  event.preventDefault()
  stopManagedBackend().finally(() => {
    app.quit()
  })
})

app.on('window-all-closed', () => {
  if (petUpdateTimer) {
    clearInterval(petUpdateTimer)
    petUpdateTimer = null
  }
  if (monitoringStateTimer) {
    clearInterval(monitoringStateTimer)
    monitoringStateTimer = null
  }
  app.quit()
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow()
  }
})