import { useState, useEffect } from "react";
import { useOutletContext, useSearchParams } from "react-router";
import { useAppBridge } from "@shopify/app-bridge-react";
import {
  Page,
  Layout,
  Card,
  Text,
  BlockStack,
  InlineStack,
  Icon,
  Box,
  Spinner,
  Button,
} from "@shopify/polaris";
import { SearchIcon, ArrowLeftIcon, EmailIcon } from "@shopify/polaris-icons";
import "../styles/app.css";

export default function HelpCenterPage() {
  const { shop, backendUrl } = useOutletContext();
  const shopify = useAppBridge();
  const [searchParams, setSearchParams] = useSearchParams();

  const [loading, setLoading] = useState(true);
  const [articles, setArticles] = useState([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedArticle, setSelectedArticle] = useState(null);
  const [selectedCategory, setSelectedCategory] = useState("All");

  useEffect(() => {
    const fetchArticles = async () => {
      try {
        const token = await shopify.idToken();
        const response = await fetch(`${backendUrl}/api/v1/help/articles`, {
          headers: {
            Authorization: `Bearer ${token}`,
            "X-Shopify-Shop-Domain": shop,
          },
        });
        const data = await response.json();
        if (Array.isArray(data)) {
          setArticles(data);
        }
      } catch (err) {
        console.error("Error fetching help articles:", err);
      } finally {
        setLoading(false);
      }
    };

    fetchArticles();
  }, [backendUrl, shop, shopify]);

  // Sync selected article with URL search parameter
  useEffect(() => {
    const articleId = searchParams.get("article");
    if (articleId && articles.length > 0) {
      const article = articles.find((a) => a.id === articleId);
      if (article) {
        setSelectedArticle(article);
      } else {
        setSelectedArticle(null);
      }
    } else if (!articleId) {
      setSelectedArticle(null);
    }
  }, [searchParams, articles]);

  const handleArticleClick = (article) => {
    setSelectedArticle(article);
    setSearchParams({ article: article.id });
  };

  const handleBackToList = () => {
    setSelectedArticle(null);
    setSearchParams({});
  };

  // Safe client-side markdown parsing
  const renderMarkdown = (text) => {
    if (!text) return "";
    let html = text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

    // Headings
    html = html.replace(/^# (.*?)$/gm, "<h1>$1</h1>");
    html = html.replace(/^## (.*?)$/gm, "<h2>$1</h2>");
    html = html.replace(/^### (.*?)$/gm, "<h3>$1</h3>");

    // Bold
    html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");

    // Lists
    html = html.replace(/^- (.*?)$/gm, "<li>$1</li>");

    // Links
    html = html.replace(/\[(.*?)\]\((.*?)\)/g, '<a class="rf-chat-msg-link" href="$2">$1</a>');

    // Line breaks
    html = html.replace(/\n/g, "<br />");

    return <div className="rf-markdown-content" dangerouslySetInnerHTML={{ __html: html }} />;
  };

  // Filter logic
  const categories = ["All", "Setup Guide", "Billing & Payments", "Recovery Campaigns", "Dashboard Metrics", "Support"];

  const filteredArticles = articles.filter((article) => {
    const matchesCategory = selectedCategory === "All" || article.category === selectedCategory;
    const matchesSearch =
      article.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      article.summary.toLowerCase().includes(searchQuery.toLowerCase()) ||
      article.content.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesCategory && matchesSearch;
  });

  return (
    <Page title="Help Center">
      <Layout>
        {selectedArticle ? (
          // Article Detail View
          <Layout.Section>
            <div className="rf-help-article-detail">
              <button className="rf-help-back-button" onClick={handleBackToList}>
                <Icon source={ArrowLeftIcon} tone="base" />
                Back to all guides
              </button>
              <Box paddingBlockEnd="400">
                <Text variant="headingSm" as="span" tone="subdued">
                  {selectedArticle.category}
                </Text>
              </Box>
              {renderMarkdown(selectedArticle.content)}
            </div>
          </Layout.Section>
        ) : (
          // Main Help Center Grid
          <>
            <Layout.Section>
              <div className="rf-help-header">
                <Text variant="headingXl" as="h1">
                  How can we help you today?
                </Text>
                <div className="rf-help-search-wrapper">
                  <span className="rf-help-search-icon">
                    <Icon source={SearchIcon} tone="base" />
                  </span>
                  <input
                    type="text"
                    className="rf-help-search-input"
                    placeholder="Search guides, billing concepts, campaigns..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                  />
                </div>
              </div>
            </Layout.Section>

            {/* Category Filter Pills */}
            <Layout.Section>
              <InlineStack gap="200" align="center">
                {categories.map((cat) => (
                  <button
                    key={cat}
                    className={`rf-plan-button ${selectedCategory === cat ? "active" : ""}`}
                    style={{ width: "auto", padding: "0.5rem 1rem", fontSize: "0.85rem" }}
                    onClick={() => setSelectedCategory(cat)}
                  >
                    {cat}
                  </button>
                ))}
              </InlineStack>
            </Layout.Section>

            {/* List of articles */}
            <Layout.Section>
              {loading ? (
                <Box padding="800" align="center">
                  <Spinner size="large" />
                </Box>
              ) : filteredArticles.length > 0 ? (
                <div className="rf-help-articles-list">
                  {filteredArticles.map((article) => (
                    <div
                      key={article.id}
                      className="rf-help-article-item"
                      onClick={() => handleArticleClick(article)}
                    >
                      <div className="rf-help-article-title">{article.title}</div>
                      <div className="rf-help-article-summary">{article.summary}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <Box padding="800" align="center">
                  <Text variant="bodyMd" as="p" tone="subdued">
                    No articles found matching "{searchQuery}".
                  </Text>
                </Box>
              )}
            </Layout.Section>

            {/* support card */}
            <Layout.Section variant="oneThird">
              <Card>
                <BlockStack gap="300">
                  <InlineStack gap="200" align="start">
                    <Icon source={EmailIcon} tone="base" />
                    <Text variant="headingMd" as="h2">
                      Need custom support?
                    </Text>
                  </InlineStack>
                  <Text variant="bodyMd" as="p" tone="subdued">
                    Have questions about specific configurations or custom invoice setups?
                  </Text>
                  <Text variant="bodyMd" as="p" fontWeight="bold">
                    Email us at Support.emplabs@gmail.com
                  </Text>
                  <Button variant="secondary" onClick={() => {
                    localStorage.removeItem("rf_tour_completed");
                    shopify.toast.show("Onboarding tour reset! Return to the Dashboard to take the tour.");
                  }}>
                    Restart Onboarding Tour
                  </Button>
                </BlockStack>
              </Card>
            </Layout.Section>
          </>
        )}
      </Layout>
    </Page>
  );
}
