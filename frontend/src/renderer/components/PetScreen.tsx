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

  const mockFocused = () => {
    setMonitoringState({
      timestamp: new Date().toISOString(),
      kpmValue: 112,
      label: 'Focused',
      confidence: 0.96,
      appName: 'Code',
    });
    setPetVisible(true);
    setPetEmotion('play');
    setPetMessage('You have been focused for a long time! Great job!');
  };

  const mockIdleReminder = () => {
    setMonitoringState({
      timestamp: new Date().toISOString(),
      kpmValue: 0,
      label: 'Idle',
      confidence: 1,
      appName: 'Notes',
    });
    setPetVisible(true);
    setPetEmotion('idle');
    setPetMessage('Looks like you need a short break.');
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
            <button className="secondary-button" onClick={mockFocused}>
              Mock Focused
            </button>
            <button className="secondary-button" onClick={mockIdleReminder}>
              Mock Idle
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
        <button className="secondary-button" onClick={mockFocused}>
          Mock Focused
        </button>
        <button className="secondary-button" onClick={mockIdleReminder}>
          Mock Idle
        </button>
        <button className="secondary-button" onClick={mockHidden}>
          Hide Pet
        </button>
      </div>
    </div>
  );
}