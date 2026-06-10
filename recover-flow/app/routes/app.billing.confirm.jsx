import { useEffect, useState } from "react";
import { useLoaderData, useOutletContext, useNavigate } from "react-router";
import { useAppBridge } from "@shopify/app-bridge-react";
import {
  Page,
  Layout,
  Card,
  Text,
  Spinner,
  BlockStack,
  Banner,
  Box,
  Button,
} from "@shopify/polaris";
import { authenticate } from "../shopify.server";

export const loader = async ({ request }) => {
  const { admin } = await authenticate.admin(request);
  const url = new URL(request.url);
  const chargeId = url.searchParams.get("charge_id");
  const plan = url.searchParams.get("plan");
  
  if (!chargeId) {
    return { success: false, error: "Missing charge ID from Shopify redirect" };
  }

  // 1. If 'plan' is in the query parameters, this is a Subscription Confirmation
  if (plan) {
    const addCredits = parseInt(url.searchParams.get("add_credits") || "0", 10);
    try {
      const response = await admin.graphql(
        `#graphql
        query getSubscription($id: ID!) {
          node(id: $id) {
            ... on AppSubscription {
              status
              name
            }
          }
        }`,
        { variables: { id: chargeId } }
      );

      const responseJson = await response.json();
      const subscription = responseJson.data?.node;

      if (subscription?.status === "ACTIVE") {
        return {
          success: true,
          isSubscription: true,
          chargeId,
          plan,
          addCredits,
        };
      } else {
        return {
          success: false,
          error: `Subscription verification failed: status is ${subscription?.status || "unknown"}`,
        };
      }
    } catch (err) {
      console.error("Subscription Loader Exception:", err);
      return { success: false, error: "Failed to verify subscription with Shopify" };
    }
  }

  // 2. Otherwise, this is a One-Time Credit Recharge Confirmation
  const pack = url.searchParams.get("pack") || "starter";
  const credits = parseInt(url.searchParams.get("credits") || "0", 10);
  const price = parseFloat(url.searchParams.get("price") || "0.0");

  try {
    const response = await admin.graphql(
      `#graphql
      query getCharge($id: ID!) {
        node(id: $id) {
          ... on AppPurchaseOneTime {
            status
            name
            price {
              amount
              currencyCode
            }
          }
        }
      }`,
      { variables: { id: chargeId } }
    );

    const responseJson = await response.json();
    const charge = responseJson.data?.node;

    if (charge?.status === "ACTIVE") {
      return {
        success: true,
        isSubscription: false,
        chargeId,
        pack,
        credits,
        price,
      };
    } else {
      return {
        success: false,
        error: `Payment verification failed: charge status is ${charge?.status || "unknown"}`,
      };
    }
  } catch (err) {
    console.error("Verification Loader Exception:", err);
    return { success: false, error: "Failed to verify transaction with Shopify" };
  }
};

export default function BillingConfirmPage() {
  const loaderData = useLoaderData();
  const { shop, backendUrl } = useOutletContext();
  const shopify = useAppBridge();
  const navigate = useNavigate();

  const [statusMessage, setStatusMessage] = useState("Verifying payment transaction...");
  const [error, setError] = useState(null);

  useEffect(() => {
    async function executeVerification() {
      if (!loaderData.success) {
        setError(loaderData.error || "Payment verification failed.");
        setStatusMessage("");
        return;
      }

      const token = await shopify.idToken();

      // Case A: Subscription Confirmation
      if (loaderData.isSubscription) {
        setStatusMessage("Activating your subscription plan...");
        try {
          const response = await fetch(`${backendUrl}/api/v1/billing/confirm-subscription`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${token}`,
              "X-Shopify-Shop-Domain": shop,
            },
            body: JSON.stringify({
              shopify_charge_id: loaderData.chargeId,
              plan: loaderData.plan,
              add_credits: loaderData.addCredits,
            }),
          });

          const data = await response.json();

          if (data.status === "success") {
            shopify.toast.show(`Subscribed to ${loaderData.plan.toUpperCase()} plan!`);

            // If they opted for additional bundled credits, redirect to one-time charge authorization
            if (loaderData.addCredits > 0) {
              setStatusMessage("Preparing credit package purchase...");
              
              let packName = "starter";
              if (loaderData.addCredits === 1000) packName = "growth";
              if (loaderData.addCredits === 5000) packName = "scale";

              const rechargeResponse = await fetch(`${backendUrl}/api/v1/billing/recharge-url`, {
                method: "POST",
                headers: {
                  "Content-Type": "application/json",
                  Authorization: `Bearer ${token}`,
                  "X-Shopify-Shop-Domain": shop,
                },
                body: JSON.stringify({
                  pack: packName,
                  app_url: window.location.origin,
                }),
              });

              const rechargeData = await rechargeResponse.json();
              if (rechargeData.confirmationUrl) {
                window.top.location.href = rechargeData.confirmationUrl;
              } else {
                setError("Subscription active, but failed to initiate credit pack charge.");
                setStatusMessage("");
              }
            } else {
              navigate("/app");
            }
          } else {
            setError(data.message || "Failed to confirm subscription on backend");
            setStatusMessage("");
          }
        } catch (err) {
          console.error("Subscription confirmation error:", err);
          setError("Network issue confirming subscription.");
          setStatusMessage("");
        }
      } 
      // Case B: One-Time Credit Recharge Confirmation
      else {
        setStatusMessage("Crediting your account balance...");
        try {
          const response = await fetch(`${backendUrl}/api/v1/billing/credit-recharge`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${token}`,
              "X-Shopify-Shop-Domain": shop,
            },
            body: JSON.stringify({
              shopify_charge_id: loaderData.chargeId,
              amount: loaderData.price,
              credits: loaderData.credits,
            }),
          });

          const data = await response.json();

          if (data.status === "success") {
            shopify.toast.show(`Successfully added ${loaderData.credits} credits!`);
            navigate("/app");
          } else {
            setError(data.message || "Failed to credit account balance");
            setStatusMessage("");
          }
        } catch (err) {
          console.error("Credit recharge API error:", err);
          setError("Network connection issue with backend.");
          setStatusMessage("");
        }
      }
    }

    executeVerification();
  }, [loaderData, shop, backendUrl, shopify, navigate]);

  return (
    <Page title="Verifying Billing Action">
      <Layout>
        <Layout.Section>
          <div style={{ maxWidth: "500px", margin: "4rem auto" }}>
            {statusMessage && (
              <Card>
                <Box padding="400">
                  <BlockStack gap="400" align="center" inlineAlign="center" style={{ textAlign: "center" }}>
                    <Spinner size="large" />
                    <Text variant="headingMd" as="h3">{statusMessage}</Text>
                    <Text tone="subdued">Please do not refresh this page while we confirm details with Shopify.</Text>
                  </BlockStack>
                </Box>
              </Card>
            )}

            {error && (
              <Banner title="Billing Action Failed" tone="critical">
                <BlockStack gap="300">
                  <p>{error}</p>
                  <div>
                    <Button onClick={() => navigate("/app")}>
                      Back to Dashboard
                    </Button>
                  </div>
                </BlockStack>
              </Banner>
            )}
          </div>
        </Layout.Section>
      </Layout>
    </Page>
  );
}
