import { useAppStore } from '../store/useAppStore';

export default function SettingsPanel() {
  const { closeSettings } = useAppStore();

  return (
    <div className="panel">
      <h2>Settings</h2>
      <button onClick={closeSettings}>Close</button>
    </div>
  );
}