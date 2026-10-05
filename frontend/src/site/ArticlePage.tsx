import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ApiError, api } from "../services/api";
import { cleanTitle, formatDate, isGeneral, parseArticle } from "./articles";
import { useChatWidget } from "./ChatWidget";
import { useArticles, useTopics } from "./HomePage";
import { NotFoundPage } from "./NotFoundPage";
import { useTitle } from "./useTitle";

export function ArticlePage() {
  const { articleId = "" } = useParams();
  const { open } = useChatWidget();
  const article = useQuery({ queryKey: ["help-article", articleId], queryFn: () => api.knowledgeDetail(articleId), retry: false });
  const articles = useArticles();
  const topics = useTopics();
  const a = article.data;
  useTitle(a ? cleanTitle(a.title) : "Help article");

  if (article.error instanceof ApiError && article.error.status === 404) return <NotFoundPage />;
  if (a && a.status !== "ACTIVE") return <NotFoundPage />;
  if (article.isLoading || !a) return <div className="s-container s-page"><p className="s-muted">Loading article…</p></div>;

  const parsed = parseArticle(a.content);
  const parent = topics.data?.categories.find((c) => c.name === a.category)?.parent_name ?? a.category;
  const related = (articles.data?.items ?? []).filter((x) => x.category === a.category && x.article_id !== a.article_id && !isGeneral(x)).slice(0, 5);
  const title = cleanTitle(a.title);

  return (
    <div className="s-container s-page">
      <nav className="s-breadcrumb" aria-label="Breadcrumb">
        <Link to="/">Help center</Link><span>/</span>
        <Link to={`/help/topic/${encodeURIComponent(parent)}`}>{parent}</Link><span>/</span><span>{title}</span>
      </nav>
      <div className="s-page-grid">
        <article className="s-article">
          <h1>{title}</h1>
          <p className="s-meta">Last updated {formatDate(a.updated_at)}</p>
          {isGeneral(a) && <p className="s-callout">This is a general checklist. For help with your exact issue, chat with us and we'll take a closer look.</p>}
          {parsed.symptoms && (<><h2>What you might notice</h2><p>{parsed.symptoms}</p></>)}
          {parsed.steps.length > 0 && (
            <>
              <h2>How to fix it</h2>
              <ol className="s-steps">{parsed.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
            </>
          )}
          <div className="s-still">
            <div>
              <h3>Need a hand?</h3>
              <p>Tell us what you've tried and we'll take it from there.</p>
            </div>
            <button type="button" className="s-btn s-btn-primary"
              onClick={() => open({ message: `I followed "${title}" and would like some more help.` })}>Chat with us</button>
          </div>
        </article>
        <aside className="s-aside">
          {related.length > 0 && (
            <div className="s-aside-box plain">
              <h3>Related articles</h3>
              <ul>{related.map((r) => <li key={r.article_id}><Link to={`/help/article/${r.article_id}`}>{cleanTitle(r.title)}</Link></li>)}</ul>
            </div>
          )}
          <div className="s-aside-box plain">
            <h3>More in {parent}</h3>
            <Link to={`/help/topic/${encodeURIComponent(parent)}`}>See all {parent} articles</Link>
          </div>
        </aside>
      </div>
    </div>
  );
}
