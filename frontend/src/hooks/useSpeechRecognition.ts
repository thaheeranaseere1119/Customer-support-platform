import { useCallback, useEffect, useRef, useState } from "react";

interface RecognitionResultEvent { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }
interface RecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  onresult: ((event: RecognitionResultEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
}
type RecognitionCtor = new () => RecognitionLike;

function getCtor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export const UNSUPPORTED_MESSAGE = "Voice input is not supported in this browser.";

/** Web Speech API wrapper. Voice -> speech-to-text -> complaint text (same resolve API). */
export function useSpeechRecognition(onFinalText: (text: string) => void) {
  const [supported] = useState(() => getCtor() !== null);
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const recognition = useRef<RecognitionLike | null>(null);
  const callback = useRef(onFinalText);
  callback.current = onFinalText;

  useEffect(() => () => recognition.current?.stop(), []);

  const start = useCallback(() => {
    const Ctor = getCtor();
    if (!Ctor) {
      setError(UNSUPPORTED_MESSAGE);
      return;
    }
    try {
      const rec = new Ctor();
      rec.lang = "en-US";
      rec.continuous = false;
      rec.interimResults = true;
      rec.onresult = (event) => {
        let finalText = "";
        let interimText = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const result = event.results[i];
          if (result.isFinal) finalText += result[0].transcript;
          else interimText += result[0].transcript;
        }
        setInterim(interimText);
        if (finalText.trim()) callback.current(finalText.trim());
      };
      rec.onerror = (event) => {
        setError(event.error === "not-allowed" ? "Microphone permission was denied." : `Voice input error: ${event.error}.`);
        setListening(false);
      };
      rec.onend = () => {
        setListening(false);
        setInterim("");
      };
      recognition.current = rec;
      setError(null);
      rec.start();
      setListening(true);
    } catch {
      setError("Voice input could not start in this browser.");
      setListening(false);
    }
  }, []);

  const stop = useCallback(() => {
    recognition.current?.stop();
    setListening(false);
  }, []);

  return { supported, listening, interim, error, start, stop, clearError: () => setError(null) };
}
