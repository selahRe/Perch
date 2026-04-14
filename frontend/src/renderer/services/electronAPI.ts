declare global {
  interface Window {
    electronAPI?: {
      sendAppReady: () => Promise<any>;
      saveProfile: (data: any) => Promise<any>;
      saveSettings: (data: any) => Promise<any>;
      sendPetInteraction: (data: any) => Promise<any>;

      onProfileLoaded: (cb: (data: any) => void) => void;
      onSettingsLoaded: (cb: (data: any) => void) => void;
      onPetUpdate: (cb: (data: any) => void) => void;
      onMonitoringState: (cb: (data: any) => void) => void;
    };
  }
}

export const electronAPI = window.electronAPI;