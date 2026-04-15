import { app, BrowserWindow, ipcMain } from 'electron'
import { spawn } from 'child_process'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const BACKEND_HOST = '127.0.0.1'
const BACKEND_PORT = 8000
const WORKSPACE_ROOT = path.resolve(__dirname, '..', '..')
const VENV_PYTHON_PATH = path.join(WORKSPACE_ROOT, '.venv', 'bin', 'python')
const BACKEND_SCRIPT_PATH = path.join(WORKSPACE_ROOT, 'backend', 'main.py')
const BACKEND_EXECUTABLE_CANDIDATES = [
  path.join(process.resourcesPath, 'backend', process.platform === 'win32' ? 'backend.exe' : 'backend'),
  path.join(process.resourcesPath, process.platform === 'win32' ? 'backend.exe' : 'backend'),
  path.join(WORKSPACE_ROOT, 'backend', process.platform === 'win32' ? 'backend.exe' : 'backend'),
]

let mainWindow
let petUpdateTimer = null
let monitoringStateTimer = null
let pythonProcess = null
let backendManagedByElectron = false
let isQuitting = false
let backendBaseUrl = `http://${BACKEND_HOST}:${BACKEND_PORT}`
let pythonStdoutBuffer = ''
let pendingBackendReadyResolve = null

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function resetBackendReadyPromise() {
  return new Promise((resolve) => {
    pendingBackendReadyResolve = resolve
  })
}

function resolveBackendReady(event) {
  if (pendingBackendReadyResolve) {
    pendingBackendReadyResolve(event)
    pendingBackendReadyResolve = null
  }
}

function sendToRenderer(channel, payload) {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return
  }
  mainWindow.webContents.send(channel, payload)
}

function handleBackendEventLine(line) {
  if (!line.startsWith('PERCH_EVENT ')) {
    return false
  }

  try {
    const rawPayload = line.slice('PERCH_EVENT '.length)
    const event = JSON.parse(rawPayload)

    if (event.type === 'ready') {
      const port = Number(event.port)
      if (Number.isFinite(port) && port > 0) {
        backendBaseUrl = `http://${BACKEND_HOST}:${port}`
        console.log(`[Perch] Backend ready signal received on port ${port}`)
      }
      resolveBackendReady(event)
      return true
    }

    if (event.type === 'pet:update') {
      sendToRenderer('pet:update', event.data)
      return true
    }

    if (event.type === 'monitoring:state') {
      sendToRenderer('monitoring:state', event.data)
      return true
    }

    if (event.type === 'bridge:error') {
      console.error('[Perch] Backend bridge error event:', event.message)
      return true
    }
  } catch (error) {
    console.error('[Perch] Failed to parse backend event line:', line, error)
    return true
  }

  return false
}

function handlePythonStdoutChunk(chunk) {
  pythonStdoutBuffer += chunk.toString()
  const lines = pythonStdoutBuffer.split(/\r?\n/)
  pythonStdoutBuffer = lines.pop() || ''

  for (const line of lines) {
    if (!handleBackendEventLine(line)) {
      process.stdout.write(`[Perch:python] ${line}\n`)
    }
  }
}

function isDevelopmentMode() {
  return !app.isPackaged || process.env.NODE_ENV === 'development'
}

function resolveBackendLaunchTarget() {
  if (isDevelopmentMode()) {
    const pythonCommand =
      process.env.PERCH_BACKEND_PYTHON ||
      (fs.existsSync(VENV_PYTHON_PATH) ? VENV_PYTHON_PATH : 'python3')
    const scriptPath = process.env.PERCH_BACKEND_SCRIPT_PATH || BACKEND_SCRIPT_PATH

    if (!fs.existsSync(scriptPath)) {
      throw new Error(`[Perch] Dev backend script not found: ${scriptPath}`)
    }

    return {
      command: pythonCommand,
      args: [scriptPath],
      cwd: WORKSPACE_ROOT,
      mode: 'development',
    }
  }

  const explicitExecutable = process.env.PERCH_BACKEND_EXECUTABLE_PATH
  const executablePath = explicitExecutable
    ? explicitExecutable
    : BACKEND_EXECUTABLE_CANDIDATES.find((candidate) => fs.existsSync(candidate))

  if (!executablePath) {
    throw new Error(
      `[Perch] Production backend executable not found. Checked: ${BACKEND_EXECUTABLE_CANDIDATES.join(', ')}`
    )
  }

  return {
    command: executablePath,
    args: [],
    cwd: path.dirname(executablePath),
    mode: 'production',
  }
}

async function isBackendReachable() {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 1200)
  try {
    const response = await fetch(`${backendBaseUrl}/monitoring/state`, {
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
  backendBaseUrl = `http://${BACKEND_HOST}:${BACKEND_PORT}`

  if (await isBackendReachable()) {
    console.log('[Perch] Backend already running; lifecycle is externally managed.')
    return
  }

  const launch = resolveBackendLaunchTarget()
  console.log(
    `[Perch] Starting managed backend in ${launch.mode} mode: ${launch.command} ${launch.args.join(' ')}`
  )

  pythonProcess = spawn(
    launch.command,
    launch.args,
    {
      cwd: launch.cwd,
      stdio: ['ignore', 'pipe', 'pipe'],
    }
  )
  backendManagedByElectron = true
  pythonStdoutBuffer = ''
  const backendReadySignal = resetBackendReadyPromise()

  pythonProcess.stdout.on('data', (chunk) => {
    handlePythonStdoutChunk(chunk)
  })

  pythonProcess.stderr.on('data', (chunk) => {
    process.stderr.write(`[Perch:python] ${chunk}`)
  })

  pythonProcess.on('exit', (code, signal) => {
    resolveBackendReady({ type: 'exit', code, signal })
    if (!isQuitting) {
      console.error(`[Perch] Managed Python backend exited unexpectedly (code=${code}, signal=${signal})`)
    }
  })

  try {
    await Promise.race([
      backendReadySignal,
      sleep(12000).then(() => null),
    ])
  } catch {
    // Ready signal is optional for compatibility; reachability check below is authoritative.
  }

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
  const response = await fetch(`${backendBaseUrl}${route}`)
  if (!response.ok) {
    throw new Error(`GET ${route} failed: ${response.status}`)
  }
  return response.json()
}

async function apiPost(route, payload) {
  const response = await fetch(`${backendBaseUrl}${route}`, {
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