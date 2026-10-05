import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../services/api";
import { ChatWidgetProvider, useChatWidget } from "./ChatWidget";
import { Wordmark } from "./Logo";

function Header() {
  const { open } = useChatWidget();
  const [menu, setMenu] = useState(false);
  const { pathname } = useLocation();
  useEffect(() => setMenu(false), [pathname]);
  return (
    <header className="s-header">
      <div className="s-container s-header-inner">
        <Link to="/" className="s-brand" aria-label="Support IQ home"><Wordmark /></Link>
        <button type="button" className="s-menu-toggle" aria-expanded={menu} aria-controls="site-nav" onClick={() => setMenu((v) => !v)}>Menu</button>
        <nav id="site-nav" className={`s-nav ${menu ? "open" : ""}`} aria-label="Main">
          <NavLink to="/" end>Help center</NavLink>
          <a href="/#topics">Topics</a>
          <a href="/#contact">Contact us</a>
          <button type="button" className="s-btn s-btn-primary s-btn-sm" onClick={() => open()}>Chat with us</button>
        </nav>
      </div>
    </header>
  );
}

function Footer() {
  const { open } = useChatWidget();
  const intents = useQuery({ queryKey: ["intents"], queryFn: api.intents, staleTime: 300_000 });
  const topics = (intents.data?.categories ?? []).filter((c) => !c.parent_name).slice(0, 6);
  return (
    <footer className="s-footer">
      <div className="s-container s-footer-grid">
        <div>
          <Wordmark />
          <p>Help with your mobile, broadband, SIM and billing, any time of day.</p>
        </div>
        <div>
          <h4>Help topics</h4>
          <ul>{topics.map((t) => <li key={t.name}><Link to={`/help/topic/${encodeURIComponent(t.name)}`}>{t.name}</Link></li>)}</ul>
        </div>
        <div>
          <h4>Get in touch</h4>
          <ul>
            <li><button type="button" className="s-footer-link" onClick={() => open()}>Chat with us</button></li>
            <li><button type="button" className="s-footer-link" onClick={() => open({ human: true })}>Talk to a person</button></li>
            <li><button type="button" className="s-footer-link" onClick={() => open({ view: "requests" })}>Your support requests</button></li>
          </ul>
        </div>
        <div>
          <h4>Support IQ</h4>
          <ul>
            <li><Link to="/">Help center</Link></li>
            <li><Link to="/admin">Staff login</Link></li>
          </ul>
        </div>
      </div>
      <div className="s-container s-footer-bottom">
        <span>© {new Date().getFullYear()} Support IQ</span>
        <span>Demo website. Help articles and account data are sample data.</span>
      </div>
    </footer>
  );
}

/** Public customer website: header, page content, footer and the chat widget. */
export function SiteLayout() {
  const location = useLocation();
  const startOpen = location.pathname === "/user" || new URLSearchParams(location.search).get("chat") === "open";
  useEffect(() => {
    if (location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView({ behavior: "smooth" });
    else window.scrollTo?.(0, 0);
  }, [location.pathname, location.hash]);
  return (
    <ChatWidgetProvider initiallyOpen={startOpen}>
      <div className="site">
        <a href="#content" className="sr-only">Skip to content</a>
        <Header />
        <main id="content"><Outlet /></main>
        <Footer />
      </div>
    </ChatWidgetProvider>
  );
}
