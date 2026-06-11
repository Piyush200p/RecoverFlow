import { useState, useEffect } from "react";
import { useOutletContext, useLoaderData } from "react-router";
import { useAppBridge } from "@shopify/app-bridge-react";
import {
  Page,
  Layout,
  Banner,
  Card,
  Text,
  BlockStack,
  InlineStack,
  Badge,
  Spinner,
  Box,
  Button,
  RadioButton,
} from "@shopify/polaris";
import { authenticate } from "../shopify.server";
import WalletTab from "../components/WalletTab";
import "../styles/app.css";

export const loader = async ({ request }) => {
  const { admin } = await authenticate.admin(request);
  try {
    const response = await admin.graphql(
      `#graphql
      query getShopCurrency {
        shop {
          currencyCode
        }
      }`
    );
    const responseJson = await response.json();
    const currencyCode = responseJson.data?.shop?.currencyCode || "USD";
    return { currencyCode };
  } catch (err) {
    console.error("Error querying shop currency:", err);
    return { currencyCode: "USD" };
  }
};

export default function BillingPage() {
  const { shop, backendUrl } = useOutletContext();
  const { currencyCode } = useLoaderData();
  const shopify = useAppBridge();

  const [loading, setLoading] = useState(true);
  const [currentPlan, setCurrentPlan] = useState("FREE");
  const [creditsRemaining, setCreditsRemaining] = useState(0);

  // Subscription Selection State
  const [selectedPlan, setSelectedPlan] = useState("growth");
  const [extraCreditsPack, setExtraCreditsPack] = useState("none");
  const [subscribing, setSubscribing] = useState(false);

  // Load current store plan details
  const fetchStoreInfo = async () => {
    try {
      const token = await shopify.idToken();
      const response = await fetch(`${backendUrl}/api/v1/store`, {
        headers: {
          Authorization: `Bearer ${token}`,
          "X-Shopify-Shop-Domain": shop,
        },
      });
      const data = await response.json();
      if (data.status === "success") {
        setCurrentPlan(data.store.subscription_plan || "FREE");
        setCreditsRemaining(data.store.credits_remaining || 0);
      }
    } catch (err) {
      console.error("Error fetching store info for billing:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStoreInfo();
  }, [backendUrl, shop, shopify]);

  // Pricing values in USD
  const plans = {
    starter: { name: "Starter Plan", price: 4.99, regularPrice: 9.99, credits: 100 },
    growth: { name: "Growth Plan", price: 9.99, regularPrice: 19.99, credits: 300 },
    scale: { name: "Scale Plan", price: 29.99, regularPrice: 49.99, credits: 1000 },
  };

  const extraPacks = {
    none: { name: "No extra credits", price: 0.0, regularPrice: 0.0, credits: 0 },
    starter: { name: "500 Credits Pack", price: 4.99, regularPrice: 9.99, credits: 500 },
    growth: { name: "1000 Credits Pack", price: 9.99, regularPrice: 19.99, credits: 1000 },
    scale: { name: "5000 Credits Pack", price: 39.99, regularPrice: 69.99, credits: 5000 },
  };

  // Currency helpers
  const getExchangeRate = (code) => {
    switch (code) {
      case "INR": return 83.0;
      case "EUR": return 0.92;
      case "GBP": return 0.78;
      case "CAD": return 1.36;
      case "AUD": return 1.50;
      default: return 1.0;
    }
  };
  const getSymbol = (code) => {
    switch (code) {
      case "INR": return "₹";
      case "EUR": return "€";
      case "GBP": return "£";
      case "CAD": return "C$";
      case "AUD": return "A$";
      default: return "$";
    }
  };
  const formatLocalPrice = (usdAmount) => {
    if (currencyCode === "USD") return "";
    const rate = getExchangeRate(currencyCode);
    const symbol = getSymbol(currencyCode);
    return ` (Approx. ${symbol}${(usdAmount * rate).toFixed(0)})`;
  };

  const handleSubscribe = async () => {
    setSubscribing(true);
    try {
      const token = await shopify.idToken();
      const appUrl = `${window.location.protocol}//${window.location.host}`;
      let extraCreditsCount = extraPacks[extraCreditsPack].credits;

      const response = await fetch(`${backendUrl}/api/v1/billing/subscribe-url`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          "X-Shopify-Shop-Domain": shop,
        },
        body: JSON.stringify({
          plan: selectedPlan,
          add_credits: extraCreditsCount,
          app_url: appUrl,
        }),
      });

      const data = await response.json();
      if (response.ok && data.confirmationUrl) {
        shopify.toast.show("Redirecting to Shopify checkout...");
        window.top.location.href = data.confirmationUrl;
      } else {
        shopify.toast.show(data.detail || "Failed to initialize subscription.");
      }
    } catch (err) {
      console.error("Subscription flow failed:", err);
      shopify.toast.show("Network error initiating subscription.");
    } finally {
      setSubscribing(false);
    }
  };

  if (loading) {
    return (
      <Page title="Billing & Plans">
        <div style={{ display: "flex", justifyContent: "center", padding: "4rem" }}>
          <Spinner size="large" />
        </div>
      </Page>
    );
  }

  const selectedPlanPrice = plans[selectedPlan].price;
  const selectedExtraPrice = extraPacks[extraCreditsPack].price;

  return (
    <Page title="Billing & Credits" subtitle="Upgrade your recovery sequences and manage your credit balance">
      <Layout>
        {/* Banner */}
        <Layout.Section>
          <Banner title="Shopify Direct Billing" tone="info">
            <p>
              Subscription fees and credit purchases are processed directly on your monthly Shopify invoice. 
              No separate credit cards required.
            </p>
          </Banner>
        </Layout.Section>

        {/* Plan Selection Section */}
        <Layout.Section>
          <div style={{ marginBottom: "2rem" }}>
            <Text variant="headingXl" as="h2">Select Subscription Plan</Text>
            <Text variant="bodyMd" tone="subdued">Select the plan that fits your recovery volume and feature needs.</Text>
          </div>

          <div className="rf-billing-grid">
            {/* Starter Plan */}
            <div className={`rf-billing-card starter-card ${selectedPlan === "starter" ? "selected-card" : ""}`}>
              {currentPlan === "STARTER" && <span className="rf-popular-badge">Active Plan</span>}
              <BlockStack gap="200">
                <div className="rf-billing-title">Starter Plan</div>
                <div className="rf-trial-badge">14-Day Free Trial</div>
                <div className="rf-billing-price">
                  <div className="rf-original-price">${plans.starter.regularPrice.toFixed(2)}</div>
                  ${plans.starter.price.toFixed(2)}<span>/mo</span>
                  <div className="rf-local-price">
                    {formatLocalPrice(plans.starter.price)}
                  </div>
                </div>
                <ul className="rf-billing-features">
                  <li><strong>100</strong> Monthly Credits included</li>
                  <li>Automated Checkout Recovery</li>
                  <li>Standard Priority Dispatch Queue</li>
                </ul>
              </BlockStack>
              <div style={{ marginTop: "auto", paddingTop: "1rem" }}>
                <button
                  type="button"
                  className={`rf-plan-button ${selectedPlan === "starter" ? "active" : ""}`}
                  onClick={() => setSelectedPlan("starter")}
                  disabled={currentPlan === "STARTER"}
                >
                  {currentPlan === "STARTER" ? "Current Plan" : selectedPlan === "starter" ? "Selected" : "Choose Starter"}
                </button>
              </div>
            </div>

            {/* Growth Plan */}
            <div className={`rf-billing-card growth-card ${selectedPlan === "growth" ? "selected-card" : ""}`}>
              {currentPlan === "GROWTH" ? (
                <span className="rf-popular-badge">Active Plan</span>
              ) : (
                <span className="rf-popular-badge" style={{ background: "linear-gradient(135deg, #10b981 0%, #059669 100%)" }}>Popular</span>
              )}
              <BlockStack gap="200">
                <div className="rf-billing-title">Growth Plan</div>
                <div className="rf-trial-badge">14-Day Free Trial</div>
                <div className="rf-billing-price">
                  <div className="rf-original-price">${plans.growth.regularPrice.toFixed(2)}</div>
                  ${plans.growth.price.toFixed(2)}<span>/mo</span>
                  <div className="rf-local-price">
                    {formatLocalPrice(plans.growth.price)}
                  </div>
                </div>
                <ul className="rf-billing-features">
                  <li><strong>300</strong> Monthly Credits included</li>
                  <li>Automated Checkout Recovery</li>
                  <li><strong>Cart Abandonment Recovery</strong></li>
                  <li><strong>AI Customer Segmentation</strong></li>
                  <li>Standard Priority Dispatch Queue</li>
                </ul>
              </BlockStack>
              <div style={{ marginTop: "auto", paddingTop: "1rem" }}>
                <button
                  type="button"
                  className={`rf-plan-button ${selectedPlan === "growth" ? "active" : ""}`}
                  onClick={() => setSelectedPlan("growth")}
                  disabled={currentPlan === "GROWTH"}
                >
                  {currentPlan === "GROWTH" ? "Current Plan" : selectedPlan === "growth" ? "Selected" : "Choose Growth"}
                </button>
              </div>
            </div>

            {/* Scale Plan */}
            <div className={`rf-billing-card scale-card ${selectedPlan === "scale" ? "selected-card" : ""}`}>
              {currentPlan === "SCALE" && <span className="rf-popular-badge">Active Plan</span>}
              <BlockStack gap="200">
                <div className="rf-billing-title">Scale Plan</div>
                <div className="rf-trial-badge">14-Day Free Trial</div>
                <div className="rf-billing-price">
                  <div className="rf-original-price">${plans.scale.regularPrice.toFixed(2)}</div>
                  ${plans.scale.price.toFixed(2)}<span>/mo</span>
                  <div className="rf-local-price">
                    {formatLocalPrice(plans.scale.price)}
                  </div>
                </div>
                <ul className="rf-billing-features">
                  <li><strong>1000</strong> Monthly Credits included</li>
                  <li>Automated Checkout Recovery</li>
                  <li><strong>Cart Abandonment Recovery</strong></li>
                  <li><strong>AI Customer Segmentation</strong></li>
                  <li><strong>Dedicated Priority Queue (Unlimited Throughput)</strong></li>
                  <li>Priority Support</li>
                </ul>
              </BlockStack>
              <div style={{ marginTop: "auto", paddingTop: "1rem" }}>
                <button
                  type="button"
                  className={`rf-plan-button ${selectedPlan === "scale" ? "active" : ""}`}
                  onClick={() => setSelectedPlan("scale")}
                  disabled={currentPlan === "SCALE"}
                >
                  {currentPlan === "SCALE" ? "Current Plan" : selectedPlan === "scale" ? "Selected" : "Choose Scale"}
                </button>
              </div>
            </div>
          </div>
        </Layout.Section>

        {/* Bundle Additional Credits Section */}
        <Layout.Section variant="oneHalf">
          <Card>
            <Box padding="100">
              <BlockStack gap="400">
                <BlockStack gap="100">
                  <Text variant="headingLg" as="h3">Add Initial WhatsApp Credits</Text>
                  <Text variant="bodyMd" tone="subdued">Choose additional credit packs to bundle with your subscription.</Text>
                </BlockStack>

                <BlockStack gap="300">
                  <RadioButton
                    label={`None — use only free bundled monthly credits`}
                    checked={extraCreditsPack === "none"}
                    id="none"
                    name="extraCredits"
                    onChange={() => setExtraCreditsPack("none")}
                  />
                  <RadioButton
                    label={`500 Credits — $4.99 one-time (Was $9.99)${formatLocalPrice(4.99)}`}
                    checked={extraCreditsPack === "starter"}
                    id="starter"
                    name="extraCredits"
                    onChange={() => setExtraCreditsPack("starter")}
                  />
                  <RadioButton
                    label={`1000 Credits — $9.99 one-time (Was $19.99)${formatLocalPrice(9.99)} (10% Bonus)`}
                    checked={extraCreditsPack === "growth"}
                    id="growth"
                    name="extraCredits"
                    onChange={() => setExtraCreditsPack("growth")}
                  />
                  <RadioButton
                    label={`5000 Credits — $39.99 one-time (Was $69.99)${formatLocalPrice(39.99)} (25% Bonus)`}
                    checked={extraCreditsPack === "scale"}
                    id="scale"
                    name="extraCredits"
                    onChange={() => setExtraCreditsPack("scale")}
                  />
                </BlockStack>
              </BlockStack>
            </Box>
          </Card>
        </Layout.Section>

        {/* Order Summary & Confirm Section */}
        <Layout.Section variant="oneThird">
          <Card>
            <BlockStack gap="400">
              <Text variant="headingLg" as="h3">Checkout Summary</Text>
              
              <BlockStack gap="300">
                <InlineStack align="space-between">
                  <Text variant="bodyMd" tone="subdued">Plan Selected:</Text>
                  <Text variant="bodyMd" fontWeight="bold">{plans[selectedPlan].name}</Text>
                </InlineStack>
                
                <InlineStack align="space-between">
                  <Text variant="bodyMd" tone="subdued">Monthly Platform Fee:</Text>
                  <Text variant="bodyMd" fontWeight="bold">
                    ${selectedPlanPrice.toFixed(2)} / mo
                  </Text>
                </InlineStack>

                <InlineStack align="space-between">
                  <Text variant="bodyMd" tone="subdued">Bundled Extra Credits:</Text>
                  <Text variant="bodyMd" fontWeight="bold">
                    {extraPacks[extraCreditsPack].credits} Credits
                  </Text>
                </InlineStack>

                <InlineStack align="space-between">
                  <Text variant="bodyMd" tone="subdued">Extra Credits Charge:</Text>
                  <Text variant="bodyMd" fontWeight="bold">
                    ${selectedExtraPrice.toFixed(2)} one-time
                  </Text>
                </InlineStack>

                <Box borderBlockStartWidth="100" borderColor="border-subdued" paddingTop="300" marginTop="100">
                  <InlineStack align="space-between" blockAlign="center">
                    <BlockStack gap="100">
                      <Text variant="headingMd" as="span">Total Approval Amount</Text>
                      {currencyCode !== "USD" && (
                        <Text variant="bodySm" tone="subdued">
                          Converted dynamically by Shopify
                        </Text>
                      )}
                    </BlockStack>
                    <BlockStack gap="100" align="end">
                      <Text variant="headingLg" as="span" tone="brand">
                        ${selectedPlanPrice.toFixed(2)}/mo
                      </Text>
                      {selectedExtraPrice > 0 && (
                        <Text variant="bodySm" fontWeight="bold">
                          + ${selectedExtraPrice.toFixed(2)} one-time
                        </Text>
                      )}
                    </BlockStack>
                  </InlineStack>
                </Box>
              </BlockStack>

              <Button
                variant="primary"
                size="large"
                fullWidth
                loading={subscribing}
                onClick={handleSubscribe}
              >
                Approve & Subscribe
              </Button>
            </BlockStack>
          </Card>
        </Layout.Section>

        {/* Standalone credit recharges section */}
        <Layout.Section>
          <div style={{ marginTop: "3rem", borderTop: "1px solid var(--card-border)", paddingTop: "2rem" }}>
            <WalletTab 
              backendUrl={backendUrl}
              shop={shop}
              shopify={shopify}
              currentPlan={currentPlan}
              creditsRemaining={creditsRemaining}
              currencyCode={currencyCode}
              onRechargeComplete={fetchStoreInfo}
            />
          </div>
        </Layout.Section>
      </Layout>
    </Page>
  );
}
