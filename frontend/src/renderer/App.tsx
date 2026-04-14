import { useEffect } from 'react';
import { useAppStore } from './store/useAppStore';
import WelcomeScreen from './components/WelcomeScreen';
import UsernameScreen from './components/UsernameScreen';
import ActiveTimeScreen from './components/ActiveTimeScreen';
import PetScreen from './components/PetScreen';

export default function App() {
  const currentScreen = useAppStore((s) => s.currentScreen);
  const setScreen = useAppStore((s) => s.setScreen);
  const setName = useAppStore((s) => s.setName);
  const setActiveTime = useAppStore((s) => s.setActiveTime);
  const setPetEmotion = useAppStore((s) => s.setPetEmotion);
  const setPetMessage = useAppStore((s) => s.setPetMessage);
  const setPetVisible = useAppStore((s) => s.setPetVisible);
  const setMonitoringState = useAppStore((s) => s.setMonitoringState);

  const applyPetUpdate = (payload: any) => {
    if (typeof payload?.visible === 'boolean') {
      setPetVisible(payload.visible);
    }
    if (typeof payload?.emotion === 'string') {
      setPetEmotion(payload.emotion);
    }
    if (typeof payload?.speak === 'string') {
      setPetMessage(payload.speak);
    }
  };

  const applyMonitoringState = (state: any) => {
    setMonitoringState({
      timestamp: state?.timestamp,
      kpmValue: state?.kpm_value ?? 0,
      label: state?.status?.label ?? 'Idle',
      confidence: state?.status?.confidence ?? 1,
      appName: state?.app_name ?? null,
      currentMinuteCount: state?.current_minute_count ?? 0,
      listenerRunning: state?.listener_running ?? false,
      listenerError: state?.listener_error ?? null,
      lastKeyPressedAt: state?.last_key_pressed_at ?? null,
      lastMinuteCompletedAt: state?.last_minute_completed_at ?? null,
      samplingIntervalSeconds: state?.sampling_interval_seconds ?? 60,
    });
  };

  useEffect(() => {
    const electronAPI = window.electronAPI;

    if (!electronAPI) {
      const fetchSnapshot = async () => {
        try {
          const [petResp, monitoringResp] = await Promise.all([
            fetch('http://127.0.0.1:8000/pet/update'),
            fetch('http://127.0.0.1:8000/monitoring/state'),
          ]);
          if (petResp.ok) {
            applyPetUpdate(await petResp.json());
          }
          if (monitoringResp.ok) {
            applyMonitoringState(await monitoringResp.json());
          }
        } catch (error) {
          console.error('browser mode polling failed', error);
        }
      };

      fetchSnapshot();
      const timer = window.setInterval(fetchSnapshot, 5000);
      return () => window.clearInterval(timer);
    }

    electronAPI.onProfileLoaded((profile) => {
      if (profile?.username) {
        setName(profile.username);
      }
      if (profile?.freeTime || profile?.free_time) {
        setActiveTime(profile.freeTime || profile.free_time);
      }
      if (profile?.onboarding_completed) {
        setScreen('petHome');
      }
    });

    electronAPI.onPetUpdate((payload) => {
      applyPetUpdate(payload);
    });

    electronAPI.onMonitoringState((state) => {
      applyMonitoringState(state);
    });

    electronAPI.sendAppReady().catch((error) => {
      console.error('app:ready failed', error);
    });
  }, [setActiveTime, setName, setPetEmotion, setPetMessage, setPetVisible, setScreen, setMonitoringState]);

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