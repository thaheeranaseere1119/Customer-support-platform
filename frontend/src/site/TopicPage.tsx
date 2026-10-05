import { Link, useParams } from "react-router-dom";
import { CATEGORY_ICONS, Icon } from "../components/Icon";
import { cleanTitle, isGeneral } from "./articles";
import { useChatWidget } from "./ChatWidget";
import { useArticles, useTopics } from "./HomePage";
import { NotFoundPage } from "./NotFoundPage";
import { useTitle } from "./useTitle";

export function TopicPage() {
  const { topic = "" } = useParams();
  const name = decodeURIComponent(topic);
  const { open } = useChatWidget();
  const topics = useTopics();
  const articles = useArticles();
  useTitle(`${name} help`);
  const categories = topics.data?.categories ?? [];
  const category = categories.find((c) => c.name === name);
  if (topics.data && !category) return <NotFoundPage />;
  const family = new Set([name, ...categories.filter((c) => c.parent_name === name).map((c) => c.name)]);
  const list = (articles.data?.items ?? []).filter((a) => family.has(a.category));
  const specific = list.filter((a) => !isGeneral(a));
  const general = list.filter(isGeneral);
  const questions = (topics.data?.intents ?? []).filter((i) => family.has(i.support_category)).map((i) => i.example_complaints[0]).filter(Boolean).slice(0, 5);
  const others = categories.filter((c) => !c.parent_name && c.name !== name);

  return (
    <div className="s-container s-page">
      <nav className="s-breadcrumb" aria-label="Breadcrumb"><Link to="/">Help center</Link><span>/</span><span>{name}</span></nav>
      <div className="s-page-grid">
        <div>
          <div className="s-page-title">
            <span className="s-topic-icon large"><Icon name={CATEGORY_ICONS[name] ?? "tag"} size={24} /></span>
            <div><h1>{name}</h1><p className="s-lead">{category?.description}</p></div>
          </div>
          <h2 className="s-h3">Articles</h2>
          <ul className="s-article-list">
            {[...specific, ...general].map((a) => (
              <li key={a.article_id}><Link to={`/help/article/${a.article_id}`}>{cleanTitle(a.title)}<Icon name="arrow" size={16} /></Link></li>))}
            {articles.isLoading && <li className="s-muted">Loading articles…</li>}
            {!articles.isLoading && list.length === 0 && <li className="s-muted">Our assistant can help with anything in this topic.</li>}
          </ul>
          {questions.length > 0 && (
            <>
              <h2 className="s-h3">Common questions</h2>
              <p className="s-muted">Pick one to ask our assistant straight away.</p>
              <div className="s-question-list">
                {questions.map((q) => <button key={q} type="button" onClick={() => open({ message: q })}>{q}</button>)}
              </div>
            </>
          )}
        </div>
        <aside className="s-aside">
          <div className="s-aside-box">
            <h3>Looking for something else?</h3>
            <p>Chat with us and describe the problem in your own words.</p>
            <button type="button" className="s-btn s-btn-primary" onClick={() => open()}>Chat with us</button>
          </div>
          <div className="s-aside-box plain">
            <h3>Other topics</h3>
            <ul>{others.map((c) => <li key={c.name}><Link to={`/help/topic/${encodeURIComponent(c.name)}`}>{c.name}</Link></li>)}</ul>
          </div>
        </aside>
      </div>
    </div>
  );
}
