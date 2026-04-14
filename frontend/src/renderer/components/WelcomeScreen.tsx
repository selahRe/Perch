import { useAppStore } from '../store/useAppStore';

export default function WelcomeScreen() {
  const setScreen = useAppStore((s) => s.setScreen);

  return (
    <div className="screen welcome-screen">
      <div className="cat-face">
        <div className="cat-ear left-ear" />
        <div className="cat-ear right-ear" />
        <div className="cat-eyes">
          <span />
          <span />
        </div>
        <div className="cat-mouth">﹀</div>
      </div>

      <h1 className="title">Hi! I&apos;m your new desktop companion.</h1>
      <p className="subtitle">
        I&apos;m here to keep you company and help you stay balanced throughout your day.
      </p>

      <button className="primary-button" onClick={() => setScreen('username')}>
        Let&apos;s get started
      </button>
    </div>
  );
}