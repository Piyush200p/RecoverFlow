import { useState, useEffect } from "react";
import { useOutletContext, useNavigate } from "react-router";
import { useAppBridge } from "@shopify/app-bridge-react";
import { 
  Page, 
  Layout, 
  Grid, 
  Card, 
  Text, 
  Badge, 
  IndexTable, 
  BlockStack, 
  InlineStack, 
  Button, 
  Spinner,
  Box
} from "@shopify/polaris";
import { authenticate } from "../shopify.server";
import OnboardingTour from "../components/OnboardingTour";

export const loader = async ({ request }) => {
  await authenticate.admin(request);
  return null;
};

export default function DashboardPage() {
  const { shop, backendUrl } = useOutletContext();
  const shopify = useAppBridge();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [metrics, setMetrics] = useState(null);
  const [checkouts, setCheckouts] = useState([]);
  const [messages, setMessages] = useState([]);

  // Fetch all dashboard data
  useEffect(() => {
    async function fetchDashboardData() {
      try {
        const token = await shopify.idToken();

        // 1. Fetch ROI Metrics
        const metricsRes = await fetch(`${backendUrl}/api/v1/dashboard`, {
          headers: {
            Authorization: `Bearer ${token}`,
            "X-Shopify-Shop-Domain": shop,
          },
        });
        const metricsData = await metricsRes.json();

        // 2. Fetch Recent Checkouts
        const checkoutsRes = await fetch(`${backendUrl}/api/v1/dashboard/checkouts?limit=5`, {
          headers: {
            Authorization: `Bearer ${token}`,
            "X-Shopify-Shop-Domain": shop,
          },
        });
        const checkoutsData = await checkoutsRes.json();

        // 3. Fetch Recent Messages
        const messagesRes = await fetch(`${backendUrl}/api/v1/dashboard/messages?limit=5`, {
          headers: {
            Authorization: `Bearer ${token}`,
            "X-Shopify-Shop-Domain": shop,
          },
        });
        const messagesData = await messagesRes.json();

        if (metricsData.status === "success") {
          setMetrics(metricsData.metrics);
        }
        if (checkoutsData.status === "success") {
          setCheckouts(checkoutsData.checkouts);
        }
        if (messagesData.status === "success") {
          setMessages(messagesData.messages);
        }
      } catch (err) {
        console.error("Error fetching dashboard data:", err);
        shopify.toast.show("Error loading dashboard data");
      } finally {
        setLoading(false);
      }
    }

    fetchDashboardData();
  }, [shopify, backendUrl, shop]);

  const formatCurrency = (amount, currencyCode = "INR") => {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: currencyCode,
      maximumFractionDigits: 0,
    }).format(amount);
  };

  const getStatusBadge = (status) => {
    const statusUpper = status?.toUpperCase() || "PENDING";
    switch (statusUpper) {
      case "RECOVERED":
        return <Badge tone="success">Recovered</Badge>;
      case "PROCESSING":
        return <Badge tone="info">Processing</Badge>;
      case "PENDING":
        return <Badge tone="default">Pending</Badge>;
      case "FAILED":
        return <Badge tone="critical">Failed</Badge>;
      case "EXHAUSTED":
        return <Badge tone="attention">Exhausted</Badge>;
      default:
        return <Badge>{status}</Badge>;
    }
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return "-";
    const date = new Date(dateStr);
    return date.toLocaleDateString("en-IN", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  if (loading) {
    return (
      <Page title="Dashboard">
        <Layout>
          <Layout.Section>
            <div style={{ display: "flex", justifyContent: "center", padding: "4rem" }}>
              <Spinner size="large" />
            </div>
          </Layout.Section>
        </Layout>
      </Page>
    );
  }

  const getSegmentBadge = (segment) => {
    if (!segment) return <Badge tone="neutral">Standard</Badge>;
    const formatted = segment.replace(/_/g, " ");
    switch (segment.toUpperCase()) {
      case "FIRST_TIME":
        return <Badge tone="info">First-Time</Badge>;
      case "RETURNING":
        return <Badge tone="neutral">Returning</Badge>;
      case "VIP":
        return <Badge tone="magic">VIP</Badge>;
      case "HIGH_VALUE":
        return <Badge tone="warning">High Value</Badge>;
      case "DISCOUNT_ORIENTED":
        return <Badge tone="attention">Discount</Badge>;
      case "LIKELY_TO_PURCHASE":
        return <Badge tone="success">Likely Buyer</Badge>;
      default:
        return <Badge>{formatted}</Badge>;
    }
  };

  // Row markups for checkouts table
  const checkoutRows = checkouts.map((checkout, index) => (
    <IndexTable.Row id={checkout.checkout_id} key={checkout.checkout_id} position={index}>
      <IndexTable.Cell>
        <Text fontWeight="bold" as="span">{checkout.customer_name || "Unknown"}</Text>
        <div style={{ fontSize: "12px", color: "var(--p-text-secondary)" }}>
          {checkout.customer_phone || "No phone"}
        </div>
      </IndexTable.Cell>
      <IndexTable.Cell>{getSegmentBadge(checkout.customer_segment)}</IndexTable.Cell>
      <IndexTable.Cell>{formatCurrency(checkout.total_price, checkout.currency)}</IndexTable.Cell>
      <IndexTable.Cell>{getStatusBadge(checkout.recovery_status)}</IndexTable.Cell>
      <IndexTable.Cell>{formatDate(checkout.created_at)}</IndexTable.Cell>
    </IndexTable.Row>
  ));

  // Row markups for messages table
  const messageRows = messages.map((msg, index) => (
    <IndexTable.Row id={msg.id.toString()} key={msg.id} position={index}>
      <IndexTable.Cell>
        <Text fontWeight="bold" as="span">{msg.customer_name || "Unknown"}</Text>
        <div 
          style={{ 
            fontSize: "12px", 
            color: "var(--p-text-secondary)",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            overflow: "hidden",
            maxWidth: "180px"
          }}
          title={msg.message_body}
        >
          {msg.message_body}
        </div>
      </IndexTable.Cell>
      <IndexTable.Cell>Step {msg.step_number}</IndexTable.Cell>
      <IndexTable.Cell>{getStatusBadge(msg.status)}</IndexTable.Cell>
      <IndexTable.Cell>{formatDate(msg.sent_at)}</IndexTable.Cell>
    </IndexTable.Row>
  ));

  return (
    <Page 
      title="Dashboard" 
      subtitle="Real-time revenue recovery and WhatsApp campaign analytics"
      primaryAction={
        <Button variant="primary" onClick={() => navigate("/app/billing")}>
          Recharge Credits
        </Button>
      }
    >
      <Layout>
        {/* Top notification if low credits */}
        {(metrics?.credits_remaining ?? 0) < 10 && (
          <Layout.Section>
            <Box padding="400" background="bg-surface-critical-subdued" borderRadius="200">
              <InlineStack align="space-between" blockAlign="center">
                <Text tone="critical" fontWeight="bold">
                  ⚠️ Critical Balance: You only have {metrics?.credits_remaining} WhatsApp recovery credits left.
                </Text>
                <Button variant="primary" tone="critical" size="small" onClick={() => navigate("/app/billing")}>
                  Recharge Now
                </Button>
              </InlineStack>
            </Box>
          </Layout.Section>
        )}

        {/* KPI Grid */}
        <Layout.Section>
          <div id="tour-roi">
            <Grid>
              <Grid.Cell columnSpan={{ xs: 6, sm: 6, md: 3, lg: 3, xl: 3 }}>
                <Card>
                  <BlockStack gap="100">
                    <Text variant="headingSm" tone="subdued">Recovered Revenue</Text>
                    <Text variant="heading2xl" as="h2" tone="success">
                      {formatCurrency(metrics?.recovered_revenue ?? 0)}
                    </Text>
                    <Text variant="bodyXs" tone="subdued">
                      From {metrics?.recovered_orders ?? 0} recovered carts
                    </Text>
                  </BlockStack>
                </Card>
              </Grid.Cell>

              <Grid.Cell columnSpan={{ xs: 6, sm: 6, md: 3, lg: 3, xl: 3 }}>
                <Card>
                  <BlockStack gap="100">
                    <Text variant="headingSm" tone="subdued">Recovery Rate</Text>
                    <Text variant="heading2xl" as="h2">
                      {metrics?.recovery_rate ?? 0.0}%
                    </Text>
                    <Text variant="bodyXs" tone="subdued">
                      {metrics?.recovered_orders ?? 0} out of {metrics?.total_abandoned_carts ?? 0} checkouts
                    </Text>
                  </BlockStack>
                </Card>
              </Grid.Cell>

              <Grid.Cell columnSpan={{ xs: 6, sm: 6, md: 3, lg: 3, xl: 3 }}>
                <Card>
                  <BlockStack gap="100">
                    <Text variant="headingSm" tone="subdued">Opportunity Score</Text>
                    <Text variant="heading2xl" as="h2" tone="warning">
                      {formatCurrency(metrics?.recoverable_revenue_estimate ?? 0)}
                    </Text>
                    <Text variant="bodyXs" tone="subdued">
                      Estimated recoverable lost revenue
                    </Text>
                  </BlockStack>
                </Card>
              </Grid.Cell>

              <Grid.Cell columnSpan={{ xs: 6, sm: 6, md: 3, lg: 3, xl: 3 }}>
                <div id="tour-credits">
                  <Card>
                    <BlockStack gap="100">
                      <Text variant="headingSm" tone="subdued">Credits Remaining</Text>
                      <Text variant="heading2xl" as="h2" tone={(metrics?.credits_remaining ?? 0) < 10 ? "critical" : "subdued"}>
                        {metrics?.credits_remaining ?? 0}
                      </Text>
                      <Text variant="bodyXs" tone="subdued">
                        Total messages sent: {metrics?.messages_sent ?? 0}
                      </Text>
                    </BlockStack>
                  </Card>
                </div>
              </Grid.Cell>
            </Grid>
          </div>
        </Layout.Section>

        {/* Abandoned Checkouts and Message Logs */}
        <div id="tour-logs" style={{ display: 'contents' }}>
          <Layout.Section variant="oneHalf">
            <Card padding="0">
              <Box padding="400">
                <BlockStack gap="200">
                  <Text variant="headingMd" as="h3">Recent Abandoned Carts</Text>
                  {checkouts.length === 0 ? (
                    <div style={{ padding: "2rem", textAlign: "center" }}>
                      <Text tone="subdued">No abandoned checkouts found.</Text>
                    </div>
                  ) : (
                    <IndexTable
                      resourceName={{ singular: "checkout", plural: "checkouts" }}
                      itemCount={checkouts.length}
                      headings={[
                        { title: "Customer" },
                        { title: "Segment" },
                        { title: "Total" },
                        { title: "Status" },
                        { title: "Date" },
                      ]}
                      selectable={false}
                    >
                      {checkoutRows}
                    </IndexTable>
                  )}
                </BlockStack>
              </Box>
            </Card>
          </Layout.Section>

          <Layout.Section variant="oneHalf">
            <Card padding="0">
              <Box padding="400">
                <BlockStack gap="200">
                  <Text variant="headingMd" as="h3">Recent Sent Reminders</Text>
                  {messages.length === 0 ? (
                    <div style={{ padding: "2rem", textAlign: "center" }}>
                      <Text tone="subdued">No recovery messages sent yet.</Text>
                    </div>
                  ) : (
                    <IndexTable
                      resourceName={{ singular: "message", plural: "messages" }}
                      itemCount={messages.length}
                      headings={[
                        { title: "Customer" },
                        { title: "Step" },
                        { title: "Status" },
                        { title: "Time" },
                      ]}
                      selectable={false}
                    >
                      {messageRows}
                    </IndexTable>
                  )}
                </BlockStack>
              </Box>
            </Card>
          </Layout.Section>
        </div>

      </Layout>
      <OnboardingTour />
    </Page>
  );
}
