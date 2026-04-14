import { useState } from 'react';
import { useAppStore } from '../store/useAppStore';

export default function OnboardingModal() {
  const { closeOnboarding } = useAppStore();

  const [name, setName] = useState('');

  const handleSave = () => {
    window.electronAPI?.saveProfile({
      name,
      gender: 'prefer_not_to_say',
      freeTime: '',
      reminders: {
        hydration: true,
        stretching: true,
        meetings: true,
      },
    });

    closeOnboarding();
  };

  return (
    <div className="modal">
      <h2>Hi! I'm your pet</h2>
      <input
        placeholder="your name"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <button onClick={handleSave}>Start</button>
    </div>
  );
}