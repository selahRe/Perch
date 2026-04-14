import { useEffect } from 'react';
import { useAppStore } from './store/useAppStore';
import WelcomeScreen from './components/WelcomeScreen';
import UsernameScreen from './components/UsernameScreen';
import ActiveTimeScreen from './components/ActiveTimeScreen';
import PetScreen from './components/PetScreen';
import { electronAPI } from './services/electronAPI';

export default function App() {
  const currentScreen = useAppStore((s) => s.currentScreen);
  const setScreen = useAppStore((s) => s.setScreen);
  const setName = useAppStore((s) => s.setName);
  const setPetEmotion = useAppStore((s) => s.setPetEmotion);
  const setPetMessage = useAppStore((s) => s.setPetMessage);
  const setPetVisible = useAppStore((s) => s.setPetVisible);

  useEffect(() => {
    if (!electronAPI) {
      return;
    }

    electronAPI.onProfileLoaded((profile) => {
      if (profile?.username) {
        setName(profile.username);
      }
      if (profile?.onboarding_completed) {
        setScreen('petHome');
      }
    });

    electronAPI.onPetUpdate((payload) => {
      if (typeof payload?.visible === 'boolean') {
        setPetVisible(payload.visible);
      }
      if (typeof payload?.emotion === 'string') {
        setPetEmotion(payload.emotion);
      }
      if (typeof payload?.speak === 'string') {
        setPetMessage(payload.speak);
      }
    });

    electronAPI.sendAppReady().catch((error) => {
      console.error('app:ready failed', error);
    });
  }, [setName, setPetEmotion, setPetMessage, setPetVisible, setScreen]);

  if (currentScreen === 'welcome') {
    return <WelcomeScreen />;
  }

  if (currentScreen === 'username') {
    return <UsernameScreen />;
  }

  if (currentScreen === 'activeTime') {
    return <ActiveTimeScreen />;
  }

  return <PetScreen />;
}