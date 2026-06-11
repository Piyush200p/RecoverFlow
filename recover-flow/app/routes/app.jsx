import { useState, useRef, useEffect } from "react";
import { Outlet, useLoaderData, useRouteError, useLocation, Link, useNavigate } from "react-router";
import { boundary } from "@shopify/shopify-app-react-router/server";
import { AppProvider as ShopifyAppProvider } from "@shopify/shopify-app-react-router/react";
import { AppProvider as PolarisProvider, Frame, Navigation } from "@shopify/polaris";
import { HomeIcon, SettingsIcon, OrderIcon, QuestionCircleIcon } from "@shopify/polaris-icons";
import { useAppBridge } from "@shopify/app-bridge-react";
import enTranslations from "@shopify/polaris/locales/en.json";
import "@shopify/polaris/build/esm/styles.css";
import "../styles/app.css";
import { authenticate } from "../shopify.server";

export const loader = async ({ request }) => {
  const { session } = await authenticate.admin(request);

  return {
    apiKey: process.env.SHOPIFY_API_KEY || "",
    shop: session.shop,
    backendUrl: process.env.RECOVERFLOW_BACKEND_URL || "http://localhost:8000",
  };
};

function CustomLink({ url, children, external, ref, ...rest }) {
  if (external) {
    return (
      <a href={url} target="_blank" rel="noopener noreferrer" {...rest}>
        {children}
      </a>
    );
  }
  return (
    <Link to={url} {...rest}>
      {children}
    </Link>
  );
}

export default function App() {
  const { apiKey, shop, backendUrl } = useLoaderData();
  const location = useLocation();

  const navigationMarkup = (
    <Navigation location={location.pathname}>
      <Navigation.Section
        title="RecoverFlow AI"
        items={[
          {
            url: "/app",
            label: "Dashboard",
            icon: HomeIcon,
            selected: location.pathname === "/app",
          },
          {
            url: "/app/settings",
            label: "Settings",
            icon: SettingsIcon,
            selected: location.pathname === "/app/settings",
          },
          {
            url: "/app/billing",
            label: "Billing & Credits",
            icon: OrderIcon,
            selected: location.pathname.startsWith("/app/billing"),
          },
          {
            url: "/app/help",
            label: "Help Center",
            icon: QuestionCircleIcon,
            selected: location.pathname.startsWith("/app/help"),
          },
        ]}
      />
    </Navigation>
  );

  return (
    <ShopifyAppProvider embedded apiKey={apiKey}>
      <PolarisProvider i18n={enTranslations} linkComponent={CustomLink}>
        <Frame navigation={navigationMarkup}>
          <Outlet context={{ shop, backendUrl }} />
          {/* Render the chatbot inside the Shopify App Provider context */}
          <FloatingChatbot shop={shop} backendUrl={backendUrl} />
        </Frame>
      </PolarisProvider>
    </ShopifyAppProvider>
  );
}

function FloatingChatbot({ shop, backendUrl }) {
  const shopify = useAppBridge();
  const navigate = useNavigate();

  const [isChatOpen, setIsChatOpen] = useState(false);
  const [chatHistory, setChatHistory] = useState([
    { role: "assistant", content: "Hi! I'm your RecoverFlow Assistant. How can I help you recover revenue today?" }
  ]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);

  const messagesEndRef = useRef(null);

  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [chatHistory, chatLoading]);

  const handleSendChat = async (messageText) => {
    const textToSend = messageText || chatInput;
    if (!textToSend.trim() || chatLoading) return;

    // Add user message to history
    const userMsg = { role: "user", content: textToSend };
    setChatHistory((prev) => [...prev, userMsg]);
    setChatInput("");
    setChatLoading(true);

    try {
      const token = await shopify.idToken();
      
      const payloadHistory = chatHistory.map((m) => ({
        role: m.role,
        content: m.content,
      }));

      const response = await fetch(`${backendUrl}/api/v1/help/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          "X-Shopify-Shop-Domain": shop,
        },
        body: JSON.stringify({
          message: textToSend,
          history: payloadHistory,
        }),
      });

      const data = await response.json();
      if (data.status === "success" && data.reply) {
        setChatHistory((prev) => [...prev, { role: "assistant", content: data.reply }]);
      } else {
        setChatHistory((prev) => [
          ...prev,
          { role: "assistant", content: "I'm sorry, I encountered an error. Please contact Support.emplabs@gmail.com for help." },
        ]);
      }
    } catch (err) {
      console.error("Chatbot API error:", err);
      setChatHistory((prev) => [
        ...prev,
        { role: "assistant", content: "Failed to connect to RecoverFlow Assistant. Please try again later." },
      ]);
    } finally {
      setChatLoading(false);
    }
  };

  const suggestionChips = [
    "What is AI Segmentation?",
    "How do credits work?",
    "Which plan should I choose?",
    "How do I recharge credits?",
  ];

  const renderChatText = (text) => {
    if (!text) return "";
    let html = text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

    // Bold text (**text**)
    html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
    
    // Bullet points
    html = html.replace(/^- (.*?)$/gm, "• $1<br/>");

    // Markdown links
    html = html.replace(/\[(.*?)\]\((.*?)\)/g, '<a class="rf-chat-msg-link" href="$2" data-chat-link="true">$1</a>');

    // Line breaks
    html = html.replace(/\n/g, "<br/>");

    return (
      <div
        dangerouslySetInnerHTML={{ __html: html }}
        onClick={(e) => {
          const target = e.target;
          if (target.tagName === "A" && target.getAttribute("data-chat-link") === "true") {
            e.preventDefault();
            const href = target.getAttribute("href");
            navigate(href);
            setIsChatOpen(false);
          }
        }}
      />
    );
  };

  return (
    <>
      {/* Floating AI Assistant Drawer/Widget */}
      <button id="tour-chatbot" className="rf-chat-floating-button" onClick={() => setIsChatOpen(!isChatOpen)}>
        💬 Ask RecoverFlow
      </button>

      {isChatOpen && (
        <div className="rf-chat-window">
          <div className="rf-chat-header">
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
              <img
                src="/logo.png"
                alt="RecoverFlow Logo"
                style={{
                  width: "36px",
                  height: "36px",
                  borderRadius: "50%",
                  border: "2px solid rgba(255, 255, 255, 0.4)",
                  backgroundColor: "rgba(255, 255, 255, 0.1)",
                }}
              />
              <div className="rf-chat-title-wrapper">
                <div className="rf-chat-title">RecoverFlow Assistant</div>
                <div className="rf-chat-status">Online</div>
              </div>
            </div>
            <button className="rf-chat-close-btn" onClick={() => setIsChatOpen(false)}>
              ✕
            </button>
          </div>

          {/* Chat Message List */}
          <div className="rf-chat-messages">
            {chatHistory.map((msg, i) => (
              <div key={i} className={`rf-chat-msg ${msg.role}`}>
                {renderChatText(msg.content)}
              </div>
            ))}
            
            {chatLoading && (
              <div className="rf-chat-typing">
                <div className="rf-chat-dot" />
                <div className="rf-chat-dot" />
                <div className="rf-chat-dot" />
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Suggestion Chips */}
          <div className="rf-chat-chips-container">
            <div className="rf-chat-chips-title">Quick Questions</div>
            <div className="rf-chat-chips">
              {suggestionChips.map((chip) => (
                <button
                  key={chip}
                  className="rf-chat-chip"
                  onClick={() => handleSendChat(chip)}
                  disabled={chatLoading}
                >
                  {chip}
                </button>
              ))}
            </div>
          </div>

          {/* Chat Input Area */}
          <div className="rf-chat-input-wrapper">
            <input
              type="text"
              className="rf-chat-input"
              placeholder="Ask a question..."
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSendChat();
              }}
              disabled={chatLoading}
            />
            <button
              className="rf-chat-send-btn"
              onClick={() => handleSendChat()}
              disabled={chatLoading || !chatInput.trim()}
            >
              Send
            </button>
          </div>
        </div>
      )}
    </>
  );
}

export function ErrorBoundary() {
  return boundary.error(useRouteError());
}

export const headers = (headersArgs) => {
  return boundary.headers(headersArgs);
};
