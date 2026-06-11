/**
 * RecoverFlow AI — Webhook: checkouts/create
 * =============================================
 * Receives Shopify checkout creation events and forwards
 * the payload to the FastAPI backend for abandoned cart processing.
 */
import { authenticate } from "../shopify.server";

export const action = async ({ request }) => {
  const { topic, shop, payload } = await authenticate.webhook(request);

  console.log(`[RecoverFlow] Webhook received: ${topic} from ${shop}`);
  console.log(`[RecoverFlow] Webhook payload:`, JSON.stringify(payload));

  // Forward to FastAPI backend for processing
  try {
    const backendUrl = process.env.RECOVERFLOW_BACKEND_URL || "http://127.0.0.1:8000";
    const backendSecret = process.env.BACKEND_API_SECRET || "default_local_secret";
    const response = await fetch(`${backendUrl}/webhooks/checkout-abandonment`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Shopify-Shop-Domain": shop,
        "X-Webhook-Topic": topic,
        "X-RecoverFlow-Secret": backendSecret,
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      console.error(`[RecoverFlow] Backend returned ${response.status} for ${topic}`);
    }
  } catch (error) {
    console.error(`[RecoverFlow] Failed to forward webhook to backend:`, error.message);
  }

  // Always return 200 to Shopify to prevent retry storms
  return new Response(null, { status: 200 });
};
