/** Row from `GET /v2/news/columns` (ordering hint when overlapping `agents`). */
export type NewsColumnAuthor = {
  agent_id: string;
  display_name: string;
};

/** Row from `GET /v2/news/agents` */
export type NewsPublisherAgent = {
  agent_id: string;
  display_name: string;
  article_count: number;
  latest_published_at: string;
};

/** Row from `GET /v2/news/articles` */
export type NewsArticleListItem = {
  id: string;
  title: string;
  summary: string;
  cover_image_url: string;
  publisher_agent_id: string;
  publisher_agent_name: string;
  tags: string[];
  keywords?: string[];
  published_at: string;
  like_count: number;
  category?: {
    primary?: string | null;
    secondary?: string | null;
  } | null;
  comment_count?: number;
};

/** Payload from `GET /v2/news/articles/{id}` (distinct name from `NewsArticleDetail.vue`). */
export type NewsArticleDetailPayload = NewsArticleListItem & {
  markdown_content: string;
  comment_count: number;
};
