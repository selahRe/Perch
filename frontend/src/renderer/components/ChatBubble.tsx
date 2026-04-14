interface ChatBubbleProps {
  text: string;
}

export default function ChatBubble({ text }: ChatBubbleProps) {
  if (!text) return null;

  return (
    <div className="chat-bubble">
      <div className="chat-text">{text}</div>
      <div className="chat-tail" />
    </div>
  );
}