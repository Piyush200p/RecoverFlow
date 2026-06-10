/**
 * RecoverFlow AI — Webhook: checkouts/update
 * =============================================
 * Receives Shopify checkout update events and forwards
 * to the FastAPI backend. Used to detect when carts change
 * before recovery messages are sent.
 */
import { authenticate } from "../shopify.server";

export const action = async ({ request }) => {
  const { topic, shop, payload } = await authenticate.webhook(request);

  console.log(`[RecoverFlow] Webhook received: ${topic} from ${shop}`);
  console.log(`[RecoverFlow] Webhook payload:`, JSON.stringify(payload));

  try {
    const backendUrl = process.env.RECOVERFLOW_BACKEND_URL || "http://127.0.0.1:8000";
    const response = await fetch(`${backendUrl}/webhooks/checkout-abandonment`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Shopify-Shop-Domain": shop,
        "X-Webhook-Topic": topic,
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      console.error(`[RecoverFlow] Backend returned ${response.status} for ${topic}`);
    }
  } catch (error) {
    console.error(`[RecoverFlow] Failed to forward webhook to backend:`, error.message);
  }

  return new Response(null, { status: 200 });
};
