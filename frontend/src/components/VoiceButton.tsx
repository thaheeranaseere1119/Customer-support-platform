import { UNSUPPORTED_MESSAGE, useSpeechRecognition } from "../hooks/useSpeechRecognition";
import { Icon } from "./Icon";

export function VoiceButton({ onTranscript, disabled }: { onTranscript: (text: string) => void; disabled?: boolean }) {
  const voice = useSpeechRecognition(onTranscript);
  const label = !voice.supported ? UNSUPPORTED_MESSAGE : voice.listening ? "Stop listening" : "Speak the complaint";
  return (
    <div>
      <button type="button" className={`btn btn-ghost icon-btn voice-btn ${voice.listening ? "listening" : ""}`}
        onClick={() => (voice.listening ? voice.stop() : voice.start())} disabled={disabled}
        aria-pressed={voice.listening} aria-label={label} title={label}>
        <Icon name="mic" />
      </button>
      {voice.listening && <div className="tiny muted" aria-live="polite">Listening… {voice.interim}</div>}
      {voice.error && <div className="voice-note" role="alert">{voice.error}</div>}
    </div>
  );
}
