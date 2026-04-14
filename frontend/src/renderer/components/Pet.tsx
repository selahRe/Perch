import { useAppStore } from '../store/useAppStore';

export default function Pet({ visible, state }: any) {
  const openSettings = useAppStore((s) => s.openSettings);

  if (!visible) return null;

  return (
    <div className="pet">
      <div className="pet-avatar">
        {state === 'happy' && '😺'}
        {state === 'eat' && '🍣😺'}
        {state === 'play' && '🎾😺'}
      </div>

      <div className="pet-actions">
        <button onClick={openSettings}>⚙️</button>
      </div>
    </div>
  );
}