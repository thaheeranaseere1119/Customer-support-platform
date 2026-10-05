export function ExampleComplaint({ text, onPick }: { text: string; onPick: (text: string) => void }) {
  return <button type="button" className="example-chip" onClick={() => onPick(text)}>“{text}”</button>;
}
