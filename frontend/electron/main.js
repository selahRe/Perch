import { app, BrowserWindow, ipcMain } from 'electron'
import path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const PYTHON_BACKEND_BASE_URL = 'http://127.0.0.1:8000'

let mainWindow
let petUpdateTimer = null

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

function mapLegacyProfilePayload(input = {}) {
  if ('username' in input) {
    return input
  }

  return {
    username: input.name || '',
    gender: input.gender || 'prefer_not_to_say',
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

function registerIpcHandlers() {
  ipcMain.handle('app:ready', async () => {
    const bundle = await apiGet('/config/load')
    const pet = await apiGet('/pet/update')

    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('profile:loaded', bundle.profile)
      mainWindow.webContents.send('settings:loaded', bundle.settings)
      mainWindow.webContents.send('pet:update', pet)
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
}

app.whenReady().then(() => {
  registerIpcHandlers()
  createWindow()
})

app.on('window-all-closed', () => {
  if (petUpdateTimer) {
    clearInterval(petUpdateTimer)
    petUpdateTimer = null
  }
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow()
  }
})