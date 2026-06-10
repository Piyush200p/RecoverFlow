import { useState, useEffect } from "react";
import { useOutletContext } from "react-router";
import { useAppBridge } from "@shopify/app-bridge-react";
import {
  Page,
  Layout,
  Card,
  FormLayout,
  TextField,
  Select,
  Button,
  InlineStack,
  BlockStack,
  Text,
  Spinner,
  Box,
  Banner,
  Badge,
} from "@shopify/polaris";
import WhatsappSetupTab from "../components/WhatsappSetupTab";
import "../styles/app.css";

export default function SettingsPage() {
  const { shop, backendUrl } = useOutletContext();
  const shopify = useAppBridge();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Form State
  const [isActive, setIsActive] = useState(false);
  const [cartRecoveryActive, setCartRecoveryActive] = useState(false);
  const [storeName, setStoreName] = useState("");
  const [brandTone, setBrandTone] = useState("friendly");
  const [subscriptionPlan, setSubscriptionPlan] = useState("FREE");
  
  // WhatsApp connection credentials state
  const [phoneId, setPhoneId] = useState("");
  const [accessToken, setAccessToken] = useState("");
  const [businessId, setBusinessId] = useState("");

  // Load configuration
  useEffect(() => {
    async function loadSettings() {
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
          setIsActive(data.store.is_active);
          setCartRecoveryActive(data.store.cart_recovery_active || false);
          setSubscriptionPlan(data.store.subscription_plan || "FREE");
          setStoreName(data.store.store_name || "");
          setBrandTone(data.store.brand_tone || "friendly");
          setPhoneId(data.store.whatsapp_phone_number_id || "");
          setAccessToken(data.store.whatsapp_access_token || "");
          setBusinessId(data.store.whatsapp_business_id || "");
        } else {
          shopify.toast.show("Failed to load settings");
        }
      } catch (err) {
        console.error("Error loading settings:", err);
        shopify.toast.show("Connection error to backend");
      } finally {
        setLoading(false);
      }
    }

    loadSettings();
  }, [shopify, backendUrl, shop]);

  // Handle General Settings Save (store name, voice tone, sequence active status)
  const handleSave = async () => {
    setSaving(true);
    try {
      const token = await shopify.idToken();
      const response = await fetch(`${backendUrl}/api/v1/store/settings`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          "X-Shopify-Shop-Domain": shop,
        },
        body: JSON.stringify({
          store_name: storeName,
          brand_tone: brandTone,
          is_active: isActive,
          cart_recovery_active: cartRecoveryActive,
        }),
      });
      const data = await response.json();

      if (data.status === "success") {
        shopify.toast.show("General configurations saved successfully!");
      } else {
        shopify.toast.show(data.detail || "Failed to save settings");
      }
    } catch (err) {
      console.error(err);
      shopify.toast.show("Error saving settings");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <Page title="Settings">
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

  const toneOptions = [
    { label: "😊 Friendly & Warm", value: "friendly" },
    { label: "Casual & Approachable", value: "casual" },
    { label: "⏰ Urgent & Direct (FOMO)", value: "urgent" },
    { label: "💎 Luxury & Premium", value: "luxury" },
    { label: "🎉 Playful & Witty", value: "playful" },
    { label: "💼 Professional & Trustworthy", value: "professional" },
  ];

  return (
    <Page 
      title="Settings" 
      subtitle="Configure automated WhatsApp reminders and AI settings"
    >
      <Layout>
        {/* Status Settings Banner */}
        <Layout.Section>
          <Banner
            title={isActive ? "Automated recovery sequences are active" : "Recovery sequences are paused"}
            tone={isActive ? "success" : "warning"}
            action={{
              content: isActive ? "Pause Recovery" : "Activate Recovery",
              onAction: () => setIsActive(!isActive),
            }}
          >
            <p>
              When active, RecoverFlow AI automatically schedules a three-step recovery sequence
              for every checkouts/create webhook received.
            </p>
          </Banner>
        </Layout.Section>

        {/* Left Side Settings Form & Credentials tab */}
        <Layout.Section variant="oneHalf">
          <BlockStack gap="400">
            {/* General Configurations */}
            <Card>
              <Box padding="100">
                <FormLayout>
                  <Text variant="headingMd" as="h3">General Configurations</Text>
                  
                  <TextField
                    label="Store Brand Name"
                    value={storeName}
                    onChange={setStoreName}
                    autoComplete="off"
                    placeholder="e.g. My Awesome Shop"
                  />

                  <Select
                    label="Brand Voice & AI Tone"
                    options={toneOptions}
                    value={brandTone}
                    onChange={setBrandTone}
                  />

                  <InlineStack gap="300">
                    <Button variant="primary" loading={saving} onClick={handleSave}>
                      Save General Settings
                    </Button>
                  </InlineStack>
                </FormLayout>
              </Box>
            </Card>

            {/* Cart Abandonment Recovery (Premium Feature) */}
            <Card>
              <Box padding="100">
                <BlockStack gap="300">
                  <InlineStack align="space-between" blockAlign="center">
                    <BlockStack gap="100">
                      <InlineStack gap="200" blockAlign="center">
                        <Text variant="headingMd" as="h3">Cart Abandonment Recovery</Text>
                        <Badge tone={["GROWTH", "SCALE"].includes(subscriptionPlan) ? "success" : "attention"}>
                          {["GROWTH", "SCALE"].includes(subscriptionPlan) ? "Active Plan" : "Premium Tier Needed"}
                        </Badge>
                      </InlineStack>
                      <Text variant="bodyMd" tone="subdued">
                        Recover customers who add products to their cart but do not start checkout. Sends a single WhatsApp reminder after 12-24 hours.
                      </Text>
                    </BlockStack>
                    <Button
                      variant={cartRecoveryActive ? "primary" : "secondary"}
                      disabled={!["GROWTH", "SCALE"].includes(subscriptionPlan)}
                      onClick={() => {
                        const nextVal = !cartRecoveryActive;
                        setCartRecoveryActive(nextVal);
                        shopify.toast.show(nextVal ? "Cart recovery enabled! Click 'Save General Settings' to save." : "Cart recovery disabled. Click 'Save General Settings' to save.");
                      }}
                    >
                      {cartRecoveryActive ? "Active" : "Disabled"}
                    </Button>
                  </InlineStack>
                  {!["GROWTH", "SCALE"].includes(subscriptionPlan) && (
                    <Banner tone="warning" title="Premium subscription required">
                      <p>
                        This feature requires a premium tier subscription (<strong>Growth</strong> or <strong>Scale</strong> pack).
                        Please navigate to the <strong>Wallet</strong> tab to recharge and upgrade your plan.
                      </p>
                    </Banner>
                  )}
                </BlockStack>
              </Box>
            </Card>

            {/* AI Customer Segmentation (Premium Feature) */}
            <Card>
              <Box padding="100">
                <BlockStack gap="300">
                  <InlineStack align="space-between" blockAlign="center">
                    <BlockStack gap="100">
                      <InlineStack gap="200" blockAlign="center">
                        <Text variant="headingMd" as="h3">AI Customer Segmentation</Text>
                        <Badge tone={["GROWTH", "SCALE"].includes(subscriptionPlan) ? "success" : "attention"}>
                          {["GROWTH", "SCALE"].includes(subscriptionPlan) ? "Active Plan" : "Premium Tier Needed"}
                        </Badge>
                      </InlineStack>
                      <Text variant="bodyMd" tone="subdued">
                        Automatically group customers into custom intelligence segments (e.g. VIP, High Value, Discount-Oriented) and tailor the generated WhatsApp copywriting guidelines accordingly.
                      </Text>
                    </BlockStack>
                  </InlineStack>
                  {!["GROWTH", "SCALE"].includes(subscriptionPlan) && (
                    <Banner tone="warning" title="Premium subscription required">
                      <p>
                        This feature requires a premium tier subscription (<strong>Growth</strong> or <strong>Scale</strong> pack).
                        Please navigate to the <strong>Wallet</strong> tab to recharge and upgrade your plan.
                      </p>
                    </Banner>
                  )}
                </BlockStack>
              </Box>
            </Card>

            {/* Meta WhatsApp Cloud API credentials setup component */}
            <WhatsappSetupTab
              initialPhoneId={phoneId}
              initialAccessToken={accessToken}
              initialBusinessId={businessId}
              backendUrl={backendUrl}
              shop={shop}
              shopify={shopify}
            />
          </BlockStack>
        </Layout.Section>

        {/* Right Side Info guide */}
        <Layout.Section variant="oneThird">
          <BlockStack gap="400">
            <Card>
              <BlockStack gap="200">
                <Text variant="headingSm" as="h4">How to Setup WhatsApp Cloud API</Text>
                <Text variant="bodySm" tone="subdued">
                  1. Register a developer profile on <a href="https://developers.facebook.com/" target="_blank" rel="noopener noreferrer" style={{ color: "var(--p-text-brand)" }}>Meta for Developers</a>.
                </Text>
                <Text variant="bodySm" tone="subdued">
                  2. Create an App, select the WhatsApp product, and link your business number.
                </Text>
                <Text variant="bodySm" tone="subdued">
                  3. In Business Manager, create a System User and generate a permanent access token with the <strong>whatsapp_business_messaging</strong> permission.
                </Text>
                <Text variant="bodySm" tone="subdued">
                  4. Paste the phone number ID, system access token, and business manager ID to connect.
                </Text>
              </BlockStack>
            </Card>

            <Card>
              <BlockStack gap="200">
                <Text variant="headingSm" as="h4">Seed Credits</Text>
                <Text variant="bodySm" tone="subdued">
                  All new store installs receive <strong>50 free credits</strong> automatically. Use these to verify connection settings and inspect your first few AI campaigns.
                </Text>
              </BlockStack>
            </Card>
          </BlockStack>
        </Layout.Section>
      </Layout>
    </Page>
  );
}
