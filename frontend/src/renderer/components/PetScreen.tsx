import { useAppStore } from '../store/useAppStore';
import ChatBubble from './ChatBubble';

export default function PetScreen() {
  const { name, activeTime } = useAppStore((s) => s.profile);
  const pet = useAppStore((s) => s.pet);
  const setPetMessage = useAppStore((s) => s.setPetMessage);
  const setPetEmotion = useAppStore((s) => s.setPetEmotion);

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

  if (!pet.visible) {
    return null;
  }

  return (
    <div className="pet-screen">
      <div className="pet-top-area">
        <ChatBubble text={pet.message} />
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
      </div>
    </div>
  );
}