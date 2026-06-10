import { useState } from "react";
import {
  Card,
  ResourceList,
  ResourceItem,
  InlineGrid,
  Text,
  Button,
  BlockStack,
  InlineStack,
  Badge,
  Box,
} from "@shopify/polaris";

export default function WalletTab({ 
  backendUrl, 
  shop, 
  shopify,
  currentPlan = "FREE",
  creditsRemaining = 0,
  currencyCode = "USD",
  onRechargeComplete
}) {
  const [purchasingPack, setPurchasingPack] = useState(null);

  // Pricing values in USD
  const creditPacks = [
    {
      id: "starter",
      title: "500 Credits Pack",
      credits: 500,
      price: 4.99,
      description: "Ideal for small stores verifying initial campaigns.",
      badge: null,
    },
    {
      id: "growth",
      title: "1000 Credits Pack",
      credits: 1000,
      price: 7.99,
      description: "10% bonus credits included. Most popular choice.",
      badge: "10% Bonus",
    },
    {
      id: "scale",
      title: "5000 Credits Pack",
      credits: 5000,
      price: 29.99,
      description: "25% bonus credits included. Best value for high-volume stores.",
      badge: "25% Bonus",
    },
  ];

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

  const handlePurchase = async (packId) => {
    setPurchasingPack(packId);
    try {
      const token = await shopify.idToken();
      const appUrl = `${window.location.protocol}//${window.location.host}`;

      const response = await fetch(`${backendUrl}/api/v1/billing/recharge-url`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          "X-Shopify-Shop-Domain": shop,
        },
        body: JSON.stringify({
          pack: packId,
          app_url: appUrl,
        }),
      });

      const data = await response.json();

      if (response.ok && data.confirmationUrl) {
        shopify.toast.show("Redirecting to secure Shopify checkout...");
        window.top.location.href = data.confirmationUrl;
      } else {
        shopify.toast.show(data.detail || "Failed to initialize recharge checkout.");
      }
    } catch (err) {
      console.error("Recharge checkout failed:", err);
      shopify.toast.show("Network error initializing checkout.");
    } finally {
      setPurchasingPack(null);
    }
  };

  const getMonthlyChargeLabel = () => {
    switch (currentPlan.toUpperCase()) {
      case "STARTER": return "$3.99 / mo";
      case "GROWTH": return "$7.99 / mo";
      case "SCALE": return "$24.99 / mo";
      default: return "$0.00 / mo";
    }
  };

  const renderItem = (item) => {
    const { id, title, credits, price, description, badge } = item;

    return (
      <ResourceItem
        id={id}
        accessibilityLabel={`Purchase ${title}`}
        onClick={() => {}}
      >
        <Box padding="300">
          <InlineStack align="space-between" blockAlign="center">
            <BlockStack gap="100">
              <InlineStack gap="200" blockAlign="center">
                <Text variant="headingMd" as="h4">
                  {title}
                </Text>
                {badge && <Badge tone="success">{badge}</Badge>}
              </InlineStack>
              <Text variant="bodyMd" tone="subdued">
                {description}
              </Text>
              <Text variant="bodySm" fontWeight="bold">
                {credits} WhatsApp Credits included
              </Text>
            </BlockStack>

            <InlineStack gap="300" blockAlign="center">
              <Text variant="headingLg" as="span" tone="brand">
                ${price.toFixed(2)}{formatLocalPrice(price)}
              </Text>
              <Button
                variant="primary"
                loading={purchasingPack === id}
                onClick={() => handlePurchase(id)}
              >
                Purchase Pack
              </Button>
            </InlineStack>
          </InlineStack>
        </Box>
      </ResourceItem>
    );
  };

  return (
    <InlineGrid columns={["twoThirds", "oneThird"]} gap="400">
      {/* Left Column: Recharge Card */}
      <BlockStack gap="400">
        <Card padding="0">
          <Box padding="400" borderBlockEndWidth="100" borderColor="border-subdued">
            <BlockStack gap="100">
              <Text variant="headingLg" as="h3">
                Recharge Credits
              </Text>
              <Text variant="bodyMd" tone="subdued">
                Need more credits? Buy on-demand WhatsApp credit packs anytime to keep your sequences active.
              </Text>
            </BlockStack>
          </Box>
          <ResourceList
            resourceName={{ singular: "credit pack", plural: "credit packs" }}
            items={creditPacks}
            renderItem={renderItem}
          />
        </Card>
      </BlockStack>

      {/* Right Column: Plan Summary Card */}
      <Card>
        <BlockStack gap="400">
          <Text variant="headingLg" as="h3">
            Plan & Wallet Summary
          </Text>
          <BlockStack gap="300">
            <InlineStack align="space-between">
              <Text variant="bodyMd" tone="subdued">
                Current Plan:
              </Text>
              <Text variant="bodyMd" fontWeight="bold">
                {currentPlan.charAt(0) + currentPlan.slice(1).toLowerCase()} Tier
              </Text>
            </InlineStack>
            <InlineStack align="space-between">
              <Text variant="bodyMd" tone="subdued">
                Monthly Charge:
              </Text>
              <Text variant="bodyMd" fontWeight="bold">
                {getMonthlyChargeLabel()}
              </Text>
            </InlineStack>
            <InlineStack align="space-between">
              <Text variant="bodyMd" tone="subdued">
                Credits Remaining:
              </Text>
              <Badge tone={creditsRemaining > 0 ? "success" : "critical"}>
                {creditsRemaining} Credits
              </Badge>
            </InlineStack>
            <InlineStack align="space-between">
              <Text variant="bodyMd" tone="subdued">
                Account Status:
              </Text>
              <Badge tone={currentPlan !== "FREE" ? "success" : "attention"}>
                {currentPlan !== "FREE" ? "Subscribed" : "Free Trial"}
              </Badge>
            </InlineStack>
          </BlockStack>
        </BlockStack>
      </Card>
    </InlineGrid>
  );
}
