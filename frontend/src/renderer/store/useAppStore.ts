import { create } from 'zustand';

export type Screen = 'welcome' | 'username' | 'activeTime' | 'petHome';
export type PetEmotion = 'happy' | 'eat' | 'play' | 'idle';
export type MonitoringLabel = 'Idle' | 'Relaxed' | 'Focused';

interface MonitoringState {
  timestamp?: string;
  kpmValue: number;
  label: MonitoringLabel;
  confidence: number;
  appName?: string | null;
  currentMinuteCount: number;
  listenerRunning: boolean;
  listenerError?: string | null;
  lastKeyPressedAt?: string | null;
  lastMinuteCompletedAt?: string | null;
  samplingIntervalSeconds: number;
}

interface AppState {
  currentScreen: Screen;

  profile: {
    name: string;
    activeTime: string;
  };

  pet: {
    visible: boolean;
    emotion: PetEmotion;
    message: string;
  };

  monitoring: MonitoringState;

  setScreen: (screen: Screen) => void;
  setName: (name: string) => void;
  setActiveTime: (activeTime: string) => void;
  setPetMessage: (message: string) => void;
  setPetEmotion: (emotion: PetEmotion) => void;
  setPetVisible: (visible: boolean) => void;
  setMonitoringState: (state: Partial<MonitoringState>) => void;
  finishOnboarding: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  currentScreen: 'welcome',

  profile: {
    name: '',
    activeTime: '',
  },

  pet: {
    visible: true,
    emotion: 'happy',
    message: '',
  },

  monitoring: {
    kpmValue: 0,
    label: 'Idle',
    confidence: 1,
    appName: null,
    currentMinuteCount: 0,
    listenerRunning: false,
    listenerError: null,
    lastKeyPressedAt: null,
    lastMinuteCompletedAt: null,
    samplingIntervalSeconds: 60,
  },

  setScreen: (screen) => set({ currentScreen: screen }),

  setName: (name) =>
    set((state) => ({
      profile: {
        ...state.profile,
        name,
      },
    })),

  setActiveTime: (activeTime) =>
    set((state) => ({
      profile: {
        ...state.profile,
        activeTime,
      },
    })),

  setPetMessage: (message) =>
    set((state) => ({
      pet: {
        ...state.pet,
        message,
      },
    })),

  setPetEmotion: (emotion) =>
    set((state) => ({
      pet: {
        ...state.pet,
        emotion,
      },
    })),

  setPetVisible: (visible) =>
    set((state) => ({
      pet: {
        ...state.pet,
        visible,
      },
    })),

  setMonitoringState: (statePatch) =>
    set((state) => ({
      monitoring: {
        ...state.monitoring,
        ...statePatch,
      },
    })),

  finishOnboarding: () =>
    set((state) => ({
      currentScreen: 'petHome',
    })),
}));