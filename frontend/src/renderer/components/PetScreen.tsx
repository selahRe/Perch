import { useState } from 'react';
import { useAppStore } from '../store/useAppStore';
import ChatBubble from './ChatBubble';

export default function PetScreen() {
  const { name, activeTime } = useAppStore((s) => s.profile);
  const pet = useAppStore((s) => s.pet);
  const monitoring = useAppStore((s) => s.monitoring);
  const setPetMessage = useAppStore((s) => s.setPetMessage);
  const setPetEmotion = useAppStore((s) => s.setPetEmotion);
  const setPetVisible = useAppStore((s) => s.setPetVisible);
  const setMonitoringState = useAppStore((s) => s.setMonitoringState);
  const [burstSpeedMs, setBurstSpeedMs] = useState(600);

  const handleStretch = () => {
    setPetEmotion('play');
    setPetMessage('Stretch a little?');
  };

  const handleFeed = () => {
    setPetEmotion('eat');
    setPetMessage('Yay, thank you for feeding me!');
  };

  const handleHello = () => {
    setPetEmotion('happy');
    setPetMessage(
      name
        ? `Hi ${name}! Your usual active time is ${activeTime || 'not set yet'}.`
        : 'Hi! Nice to see you again.'
    );
  };

  const mockFocusDrop = () => {
    setMonitoringState({
      timestamp: new Date().toISOString(),
      kpmValue: 10,
      label: 'Focused',
      confidence: 0.72,
      appName: 'Code',
    });
    setPetVisible(true);
    setPetEmotion('eat');
    setPetMessage('You dropped from deep focus. Want a tiny reset before the next push?');
  };

  const mockMeetingSoon = () => {
    setMonitoringState({
      timestamp: new Date().toISOString(),
      kpmValue: 18,
      label: 'Relaxed',
      confidence: 0.88,
      appName: 'Zoom',
    });
    setPetVisible(true);
    setPetEmotion('happy');
    setPetMessage('Meeting in 5 minutes. I will stay quiet and keep you on schedule.');
  };

  const mockPerformanceBurst = () => {
    const frames = [
      { kpmValue: 120, label: 'Focused' as const, emotion: 'play' as const, speak: 'Deep work mode. I am guarding your flow.' },
      { kpmValue: 18, label: 'Relaxed' as const, emotion: 'eat' as const, speak: 'Context switch happened. Breathe once, then continue.' },
      { kpmValue: 0, label: 'Idle' as const, emotion: 'happy' as const, speak: 'Tiny break detected. Shoulder roll and water?' },
      { kpmValue: 70, label: 'Focused' as const, emotion: 'play' as const, speak: 'Nice recovery. You are back in rhythm.' },
    ];
    frames.forEach((frame, idx) => {
      window.setTimeout(() => {
        setMonitoringState({
          timestamp: new Date().toISOString(),
          kpmValue: frame.kpmValue,
          label: frame.label,
          confidence: 0.9,
          appName: 'Cursor',
        });
        setPetVisible(true);
        setPetEmotion(frame.emotion);
        setPetMessage(frame.speak);
      }, idx * burstSpeedMs);
    });
  };

  const replayGreeting = async () => {
    try {
      await fetch('http://127.0.0.1:8000/ai/demo/reset-session', { method: 'POST' });
      const response = await fetch('http://127.0.0.1:8000/pet/update');
      if (!response.ok) {
        throw new Error('failed to fetch pet update');
      }
      const payload = await response.json();
      if (typeof payload.visible === 'boolean') setPetVisible(payload.visible);
      if (typeof payload.emotion === 'string') setPetEmotion(payload.emotion);
      if (typeof payload.speak === 'string') setPetMessage(payload.speak);
    } catch (error) {
      setPetMessage('Unable to replay greeting. Check backend connection.');
    }
  };

  const mockHidden = () => {
    setPetVisible(false);
    setPetMessage('');
  };

  const showPet = () => {
    setPetVisible(true);
    setPetEmotion('happy');
    setPetMessage(name ? `Hi ${name}! I'm back.` : 'Hi! I am back.');
  };

  const formatTime = (value?: string | null) => {
    if (!value) {
      return 'not yet';
    }

    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return value;
    }

    return parsed.toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  if (!pet.visible) {
    return (
      <div className="pet-screen hidden-pet-screen">
        <div className="hidden-pet-card">
          <div className="monitoring-title">Pet hidden</div>
          <div className="monitoring-row">The pet is hidden right now, but the app is still running.</div>
          <div className="monitoring-row">You can show it again anytime.</div>
          <div className="hidden-pet-actions">
            <button className="primary-button hidden-reveal-button" onClick={showPet}>
              Show Pet Again
            </button>
            <button className="secondary-button" onClick={mockFocusDrop}>
              Mock Focus Drop
            </button>
            <button className="secondary-button" onClick={mockMeetingSoon}>
              Mock Meeting +5m
            </button>
            <button className="secondary-button" onClick={mockPerformanceBurst}>
              Demo Burst x4
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="pet-screen">
      <div className="pet-top-area">
        <ChatBubble text={pet.message} />
      </div>

      <div className="monitoring-card">
        <div className="monitoring-title">Live monitoring</div>
        <div className="monitoring-row">State: {monitoring.label}</div>
        <div className="monitoring-row">KPM: {monitoring.kpmValue}</div>
        <div className="monitoring-row">App: {monitoring.appName || 'unknown'}</div>
        <div className="monitoring-row">Listener: {monitoring.listenerRunning ? 'running' : 'stopped'}</div>
        {monitoring.listenerError ? (
          <div className="monitoring-row">Listener error: {monitoring.listenerError}</div>
        ) : null}
        <div className="monitoring-row">Keys this minute: {monitoring.currentMinuteCount}</div>
        <div className="monitoring-row">Last key: {formatTime(monitoring.lastKeyPressedAt)}</div>
        <div className="monitoring-row">Last sample: {formatTime(monitoring.lastMinuteCompletedAt)}</div>
      </div>

      <div className="pet-center-area">
        <div className={`pet-avatar pet-${pet.emotion}`}>
          <div className="cat-face small">
            <div className="cat-ear left-ear" />
            <div className="cat-ear right-ear" />
            <div className="cat-eyes">
              <span />
              <span />
            </div>
            <div className="cat-mouth">﹀</div>
          </div>
        </div>
      </div>

      <div className="pet-action-bar">
        <button className="secondary-button" onClick={handleHello}>
          Say Hi
        </button>
        <button className="secondary-button" onClick={handleFeed}>
          Feed
        </button>
        <button className="secondary-button" onClick={handleStretch}>
          Stretch Reminder
        </button>
        <button className="secondary-button" onClick={mockFocusDrop}>
          Mock Focus Drop
        </button>
        <button className="secondary-button" onClick={mockMeetingSoon}>
          Mock Meeting +5m
        </button>
        <button
          className="secondary-button"
          onClick={() => setBurstSpeedMs(300)}
          style={{ fontWeight: burstSpeedMs === 300 ? 700 : 400 }}
        >
          Burst Speed 0.3s
        </button>
        <button
          className="secondary-button"
          onClick={() => setBurstSpeedMs(600)}
          style={{ fontWeight: burstSpeedMs === 600 ? 700 : 400 }}
        >
          Burst Speed 0.6s
        </button>
        <button
          className="secondary-button"
          onClick={() => setBurstSpeedMs(1000)}
          style={{ fontWeight: burstSpeedMs === 1000 ? 700 : 400 }}
        >
          Burst Speed 1.0s
        </button>
        <button className="secondary-button" onClick={mockPerformanceBurst}>
          Demo Burst x4 ({(burstSpeedMs / 1000).toFixed(1)}s)
        </button>
        <button className="secondary-button" onClick={replayGreeting}>
          Replay First Greeting
        </button>
        <button className="secondary-button" onClick={mockHidden}>
          Hide Pet
        </button>
      </div>
    </div>
  );
}
