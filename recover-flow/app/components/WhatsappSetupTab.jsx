import { useState, useEffect } from "react";
import {
  Card,
  FormLayout,
  TextField,
  Button,
  Banner,
  BlockStack,
  InlineStack,
  Text,
  Box,
} from "@shopify/polaris";

export default function WhatsappSetupTab({
  initialPhoneId = "",
  initialAccessToken = "",
  initialBusinessId = "",
  backendUrl,
  shop,
  shopify,
}) {
  const [phoneId, setPhoneId] = useState(initialPhoneId);
  const [accessToken, setAccessToken] = useState(initialAccessToken);
  const [businessId, setBusinessId] = useState(initialBusinessId);
  
  const [isConnected, setIsConnected] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [verificationError, setVerificationError] = useState("");

  // Update connection status when initial props load
  useEffect(() => {
    if (initialPhoneId && initialAccessToken && initialBusinessId) {
      setIsConnected(true);
      setPhoneId(initialPhoneId);
      setAccessToken(initialAccessToken);
      setBusinessId(initialBusinessId);
    } else {
      setIsConnected(false);
    }
  }, [initialPhoneId, initialAccessToken, initialBusinessId]);

  const handleVerifyAndSave = async () => {
    if (!phoneId.trim() || !accessToken.trim() || !businessId.trim()) {
      shopify.toast.show("Please fill in all connection fields first.");
      return;
    }

    setVerifying(true);
    setVerificationError("");

    try {
      const token = await shopify.idToken();
      const response = await fetch(`${backendUrl}/api/v1/whatsapp/config`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          "X-Shopify-Shop-Domain": shop,
        },
        body: JSON.stringify({
          whatsapp_phone_number_id: phoneId,
          whatsapp_access_token: accessToken,
          whatsapp_business_id: businessId,
        }),
      });

      const data = await response.json();

      if (response.ok && data.status === "success") {
        setIsConnected(true);
        shopify.toast.show("WhatsApp connection verified and saved successfully!");
      } else {
        setIsConnected(false);
        setVerificationError(data.detail || "Verification failed. Check credentials.");
        shopify.toast.show("Verification failed.");
      }
    } catch (err) {
      console.error("WhatsApp verification request failed:", err);
      setIsConnected(false);
      setVerificationError("Network error. Could not reach validation backend.");
      shopify.toast.show("Network connection error.");
    } finally {
      setVerifying(false);
    }
  };

  const handleDisconnect = () => {
    setIsConnected(false);
    setPhoneId("");
    setAccessToken("");
    setBusinessId("");
    shopify.toast.show("Credentials cleared locally. Please update configurations.");
  };

  return (
    <BlockStack gap="400">
      {/* 1. Dynamic UI Banners */}
      {isConnected ? (
        <Banner
          title="Active WhatsApp Communication Pipeline Connected"
          tone="success"
          action={{
            content: "Disconnect Account",
            onAction: handleDisconnect,
            destructive: true,
          }}
        >
          <p>
            Your Meta WhatsApp Cloud API credentials are fully verified. Automated cart abandonment recovery reminders will be sent natively from your business phone number.
          </p>
        </Banner>
      ) : (
        <Banner
          title="Meta Credentials Required"
          tone="warning"
        >
          <p>
            You must connect your Meta WhatsApp Cloud API credentials to deliver cart recovery notifications natively from your own brand's phone numbers. Without this, sequences will remain in pending state.
          </p>
        </Banner>
      )}

      {/* 2. Setup Inputs Card */}
      <Card>
        <Box padding="100">
          <FormLayout>
            <Text variant="headingMd" as="h3">Meta WhatsApp Credentials Setup</Text>
            
            <TextField
              label="WhatsApp Phone Number ID"
              value={phoneId}
              onChange={setPhoneId}
              autoComplete="off"
              placeholder="e.g. 104849382093"
              disabled={isConnected || verifying}
              helpText="Found on your WhatsApp Getting Started dashboard inside Meta developers portal"
            />

            <TextField
              label="System User Permanent Access Token"
              value={accessToken}
              onChange={setAccessToken}
              type="password"
              autoComplete="off"
              placeholder={isConnected ? "••••••••••••••••••••••••" : "EAAGz..."}
              disabled={isConnected || verifying}
              helpText="Long-lived System User access token with whatsapp_business_messaging permission"
            />

            <TextField
              label="Meta Business Manager ID"
              value={businessId}
              onChange={setBusinessId}
              autoComplete="off"
              placeholder="e.g. 983204928302"
              disabled={isConnected || verifying}
              helpText="The 15-digit ID of the Business Manager owning the WhatsApp Account"
            />

            {verificationError && (
              <Banner tone="critical" title="Connection Error">
                <p>{verificationError}</p>
              </Banner>
            )}

            {!isConnected && (
              <InlineStack gap="300">
                <Button 
                  variant="primary" 
                  loading={verifying} 
                  onClick={handleVerifyAndSave}
                >
                  Verify & Save Connection
                </Button>
              </InlineStack>
            )}
          </FormLayout>
        </Box>
      </Card>
    </BlockStack>
  );
}
