import { useState } from 'react';
import { useAppStore } from '../store/useAppStore';

const OPTIONS = [
  'Morning (6am - 12pm)',
  'Afternoon (12pm - 6pm)',
  'Evening (6pm - 12am)',
  'Anytime works!',
];

export default function ActiveTimeScreen() {
  const setActiveTime = useAppStore((s) => s.setActiveTime);
  const finishOnboarding = useAppStore((s) => s.finishOnboarding);
  const savedActiveTime = useAppStore((s) => s.profile.activeTime);

  const [selected, setSelected] = useState(savedActiveTime || OPTIONS[1]);

  const handleContinue = () => {
    setActiveTime(selected);

    if (window.electronAPI?.saveProfile) {
      window.electronAPI.saveProfile({
        username: useAppStore.getState().profile.name,
        gender: 'prefer_not_to_say',
        freeTime: selected,
        reminders: {
          hydration: true,
          stretching: true,
          meetings: true,
        },
        onboarding_completed: true,
        created_at: new Date().toISOString(), 
        // ?
      });
    }

    finishOnboarding();
  };

  return (
    <div className="screen form-screen">
      <div className="form-card">
        <h2 className="form-title">When do you usually have time?</h2>
        <p className="form-subtitle">To take breaks or play</p>

        <div className="option-list">
          {OPTIONS.map((option) => (
            <label key={option} className={`option-card ${selected === option ? 'selected' : ''}`}>
              <input
                type="radio"
                name="activeTime"
                checked={selected === option}
                onChange={() => setSelected(option)}
              />
              <span>{option}</span>
            </label>
          ))}
        </div>

        <button className="primary-button" onClick={handleContinue}>
          Continue
        </button>
      </div>
    </div>
  );
}