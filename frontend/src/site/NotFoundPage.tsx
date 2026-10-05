import { Link } from "react-router-dom";
import { useChatWidget } from "./ChatWidget";
import { useTitle } from "./useTitle";

export function NotFoundPage() {
  useTitle("Page moved");
  const { open } = useChatWidget();
  return (
    <section className="s-container s-notfound">
      <p className="s-eyebrow">Let's get you back on track</p>
      <h1>This page has moved</h1>
      <p>Here are the best places to go from here.</p>
      <div className="s-actions">
        <Link to="/" className="s-btn s-btn-primary">Go to the help center</Link>
        <button type="button" className="s-btn s-btn-secondary" onClick={() => open()}>Chat with us</button>
      </div>
    </section>
  );
}
