import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { CATEGORY_ICONS, Icon } from "../components/Icon";
import { api } from "../services/api";
import { cleanTitle, isGeneral, searchArticles } from "./articles";
import { useChatWidget } from "./ChatWidget";
import { HeroIllustration } from "./Illustration";
import { useTitle } from "./useTitle";

export const useArticles = () =>
  useQuery({ queryKey: ["help-articles"], queryFn: () => api.knowledge({ status: "ACTIVE", page_size: 100 }), staleTime: 60_000 });
export const useTopics = () => useQuery({ queryKey: ["intents"], queryFn: api.intents, staleTime: 300_000 });

const POPULAR_SEARCHES = ["SIM not detected", "Charged twice", "Slow broadband", "Roaming not working", "Reset password"];

function Search() {
  const articles = useArticles();
  const { open } = useChatWidget();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const results = useMemo(() => searchArticles(articles.data?.items ?? [], query), [articles.data, query]);
  const searched = query.trim().length >= 2;
  return (
    <div className="s-search">
      <form role="search" onSubmit={(e) => { e.preventDefault(); if (results[0]) navigate(`/help/article/${results[0].article_id}`); else if (searched) open({ message: query.trim() }); }}>
        <label htmlFor="help-search" className="sr-only">Search help articles</label>
        <Icon name="search" size={18} />
        <input id="help-search" type="search" placeholder="Search for help, e.g. “SIM not detected”" value={query}
          onChange={(e) => setQuery(e.target.value)} autoComplete="off" />
        <button type="submit" className="s-btn s-btn-primary">Search</button>
      </form>
      {searched && (
        <div className="s-search-results" role="region" aria-label="Search results">
          {results.map((a) => (
            <Link key={a.article_id} to={`/help/article/${a.article_id}`} className="s-result">
              <span>{cleanTitle(a.title)}</span><small>{a.category}</small>
            </Link>
          ))}
          {articles.isLoading && <p className="s-muted">Searching…</p>}
          {!articles.isLoading && results.length === 0 && <p className="s-muted">Try different words, or let our assistant help with “{query.trim()}”.</p>}
          <button type="button" className="s-result ask" onClick={() => open({ message: query.trim() })}>
            <span>Ask our assistant about “{query.trim()}”</span><Icon name="arrow" size={16} />
          </button>
        </div>
      )}
      {!searched && (
        <p className="s-popular">Popular: {POPULAR_SEARCHES.map((p, i) => (
          <span key={p}>{i > 0 && " · "}<button type="button" className="s-link-button" onClick={() => setQuery(p)}>{p}</button></span>))}</p>
      )}
    </div>
  );
}

export function HomePage() {
  useTitle("");
  const { open } = useChatWidget();
  const articles = useArticles();
  const topics = useTopics();
  const categories = useMemo(() => topics.data?.categories ?? [], [topics.data]);
  const top = categories.filter((c) => !c.parent_name);
  const counts = useMemo(() => {
    const map: Record<string, number> = {};
    (articles.data?.items ?? []).forEach((a) => {
      const parent = categories.find((c) => c.name === a.category)?.parent_name ?? a.category;
      map[parent] = (map[parent] ?? 0) + 1;
    });
    return map;
  }, [articles.data, categories]);
  const popular = useMemo(() => {
    const rank = new Map((topics.data?.intents ?? []).map((i) => [i.name, i.ticket_count + i.case_count]));
    return (articles.data?.items ?? []).filter((a) => !isGeneral(a))
      .sort((x, y) => (rank.get(y.intent) ?? 0) - (rank.get(x.intent) ?? 0)).slice(0, 8);
  }, [articles.data, topics.data]);

  return (
    <>
      <section className="s-hero">
        <div className="s-container s-hero-grid">
          <div>
            <h1>How can we help?</h1>
            <p className="s-lead">Find answers about your phone, internet, SIM and bill, or chat with us and we'll sort it out together.</p>
            <Search />
          </div>
          <HeroIllustration />
        </div>
      </section>

      <section className="s-section" id="topics">
        <div className="s-container">
          <h2>Browse by topic</h2>
          <div className="s-topic-grid">
            {top.map((c) => (
              <Link key={c.name} to={`/help/topic/${encodeURIComponent(c.name)}`} className="s-topic">
                <span className="s-topic-icon"><Icon name={CATEGORY_ICONS[c.name] ?? "tag"} size={20} /></span>
                <span><b>{c.name}</b><small>{c.description}</small></span>
                <span className="s-topic-count">{counts[c.name] ? `${counts[c.name]} article${counts[c.name] > 1 ? "s" : ""}` : ""}</span>
              </Link>
            ))}
          </div>
        </div>
      </section>

      <section className="s-section s-section-soft">
        <div className="s-container s-split">
          <div>
            <h2>Popular articles</h2>
            <p className="s-muted">Guides for the problems customers report to us most often.</p>
          </div>
          <ul className="s-article-list">
            {popular.map((a) => (
              <li key={a.article_id}><Link to={`/help/article/${a.article_id}`}>{cleanTitle(a.title)}<Icon name="arrow" size={16} /></Link></li>
            ))}
            {articles.isLoading && <li className="s-muted">Loading articles…</li>}
          </ul>
        </div>
      </section>

      <section className="s-section" id="contact">
        <div className="s-container">
          <h2>Need more help?</h2>
          <div className="s-contact-grid">
            <div className="s-contact">
              <Icon name="chat" size={22} />
              <h3>Chat with us</h3>
              <p>Our virtual assistant answers straight away, day or night, using the same guides our team uses.</p>
              <button type="button" className="s-btn s-btn-primary" onClick={() => open()}>Start a chat</button>
            </div>
            <div className="s-contact">
              <Icon name="user" size={22} />
              <h3>Talk to a person</h3>
              <p>Prefer a human? We'll connect you to the next available member of our support team in the same chat.</p>
              <button type="button" className="s-btn s-btn-secondary" onClick={() => open({ human: true })}>Ask for a person</button>
            </div>
            <div className="s-contact">
              <Icon name="folder" size={22} />
              <h3>Check a request</h3>
              <p>See the status of problems you've already reported to us in your chat.</p>
              <button type="button" className="s-btn s-btn-secondary" onClick={() => open({ view: "requests" })}>View my requests</button>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
