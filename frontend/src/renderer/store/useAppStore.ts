import { create } from 'zustand';

export type Screen = 'welcome' | 'username' | 'activeTime' | 'petHome';
export type PetEmotion = 'happy' | 'eat' | 'play' | 'idle';

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

  setScreen: (screen: Screen) => void;
  setName: (name: string) => void;
  setActiveTime: (activeTime: string) => void;
  setPetMessage: (message: string) => void;
  setPetEmotion: (emotion: PetEmotion) => void;
  setPetVisible: (visible: boolean) => void;
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
    message: 'Hi! I am Perch~',
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

  finishOnboarding: () =>
    set((state) => ({
      currentScreen: 'petHome',
      pet: {
        ...state.pet,
        message: state.profile.name
          ? `Hi ${state.profile.name}! I'm ready to keep you company.`
          : 'Hi! I am ready to keep you company.',
      },
    })),
}));