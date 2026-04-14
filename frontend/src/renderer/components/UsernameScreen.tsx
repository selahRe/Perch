import { useState } from 'react';
import { useAppStore } from '../store/useAppStore';

export default function UsernameScreen() {
  const setScreen = useAppStore((s) => s.setScreen);
  const setName = useAppStore((s) => s.setName);
  const savedName = useAppStore((s) => s.profile.name);

  const [nameInput, setNameInput] = useState(savedName);

  const handleContinue = () => {
    if (!nameInput.trim()) return;
    setName(nameInput.trim());
    setScreen('activeTime');
  };

  return (
    <div className="screen form-screen">
      <div className="form-card">
        <h2 className="form-title">What should I call you?</h2>
        <p className="form-subtitle">I&apos;d love to know your name!</p>

        <label className="input-label">Your name</label>
        <input
          className="text-input"
          type="text"
          placeholder="Enter your name"
          value={nameInput}
          onChange={(e) => setNameInput(e.target.value)}
        />

        <button
          className="primary-button"
          onClick={handleContinue}
          disabled={!nameInput.trim()}
        >
          Continue
        </button>
      </div>
    </div>
  );
}