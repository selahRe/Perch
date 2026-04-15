const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  sendAppReady: () => ipcRenderer.invoke('app:ready'),
  saveProfile: (data) => ipcRenderer.invoke('profile:save', data),
  saveSettings: (data) => ipcRenderer.invoke('settings:save', data),
  sendPetInteraction: (data) => ipcRenderer.invoke('pet:interaction', data),

  onProfileLoaded: (cb) => ipcRenderer.on('profile:loaded', (_event, data) => cb(data)),
  onSettingsLoaded: (cb) => ipcRenderer.on('settings:loaded', (_event, data) => cb(data)),
  onPetUpdate: (cb) => ipcRenderer.on('pet:update', (_event, data) => cb(data)),
  onMonitoringState: (cb) => ipcRenderer.on('monitoring:state', (_event, data) => cb(data)),
})