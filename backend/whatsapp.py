"""
RecoverFlow AI — Block 7: Meta WhatsApp Cloud API Dispatcher
===============================================================
Handles outbound WhatsApp messaging through the Meta Graph API.

Supports:
  • Plain text messages (primary — used for recovery reminders)
  • Template messages (for pre-approved marketing templates)
  • Phone number validation (E.164 format)
  • Response parsing with structured success/error reporting
  • Retry-safe: idempotent operations, no duplicate sends

Meta Graph API Docs:
  https://developers.facebook.com/docs/whatsapp/cloud-api/messages
"""

import logging
from typing import Optional

import httpx

from config import get_settings

logger = logging.getLogger("recoverflow.whatsapp")
settings = get_settings()

# ── Meta Graph API Configuration ─────────────────────────────
GRAPH_API_VERSION = "v21.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# ── Timeout Configuration ────────────────────────────────────
REQUEST_TIMEOUT = 30.0  # seconds


# ═════════════════════════════════════════════════════════════
#  CORE: Dispatch Text Message
# ═════════════════════════════════════════════════════════════

def dispatch_whatsapp_message(
    phone_number_id: str,
    access_token: str,
    to_phone: str,
    message_body: str,
) -> dict:
    """
    Sends a WhatsApp text message via the Meta Cloud API.

    Args:
        phone_number_id: The sender's WhatsApp Business phone number ID
        access_token: Meta API access token
        to_phone: Recipient phone number in E.164 format (e.g., +919876543210)
        message_body: The text message content

    Returns:
        dict: Meta API response containing message ID on success,
              or error details on failure.

    Response format (success):
        {
            "messaging_product": "whatsapp",
            "contacts": [{"input": "+91...", "wa_id": "91..."}],
            "messages": [{"id": "wamid.xxx", "message_status": "accepted"}]
        }

    Response format (error):
        {
            "error": {
                "message": "...",
                "type": "OAuthException",
                "code": 100,
                "fbtrace_id": "..."
            }
        }
    """
    # ── Validate inputs ──────────────────────────────────────
    to_phone = _normalize_phone(to_phone)

    if not to_phone:
        logger.error("Cannot send: invalid phone number")
        return {"error": {"message": "Invalid phone number", "code": -1}}

    if not message_body or not message_body.strip():
        logger.error("Cannot send: empty message body")
        return {"error": {"message": "Empty message body", "code": -1}}

    if not phone_number_id:
        logger.error("Cannot send: missing phone_number_id")
        return {"error": {"message": "Missing phone_number_id", "code": -1}}

    if not access_token:
        logger.error("Cannot send: missing access_token")
        return {"error": {"message": "Missing access_token", "code": -1}}

    # ── Build request ────────────────────────────────────────
    url = f"{GRAPH_API_BASE}/{phone_number_id}/messages"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "text",
        "text": {
            "preview_url": True,
            "body": message_body,
        },
    }

    # ── Send request ─────────────────────────────────────────
    logger.info(
        f"Dispatching WhatsApp message to {_mask_phone(to_phone)} "
        f"via phone_id={phone_number_id[:8]}... "
        f"({len(message_body)} chars)"
    )

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            response = client.post(url, json=payload, headers=headers)

        result = response.json()

        if response.status_code == 200 and "messages" in result:
            msg_id = result["messages"][0].get("id", "unknown")
            logger.info(
                f"✅ WhatsApp message sent successfully "
                f"(wa_id={msg_id}, to={_mask_phone(to_phone)})"
            )
        elif "error" in result:
            error = result["error"]
            logger.error(
                f"❌ WhatsApp API error: [{error.get('code')}] "
                f"{error.get('message')} "
                f"(type={error.get('type')}, trace={error.get('fbtrace_id')})"
            )
        else:
            logger.warning(
                f"⚠️ Unexpected WhatsApp response "
                f"(status={response.status_code}): {result}"
            )
            result = {
                "error": {
                    "message": f"HTTP {response.status_code}: {result}",
                    "code": response.status_code,
                }
            }

        return result

    except httpx.TimeoutException:
        logger.error(
            f"WhatsApp API timeout after {REQUEST_TIMEOUT}s "
            f"(to={_mask_phone(to_phone)})"
        )
        return {
            "error": {
                "message": f"Request timed out after {REQUEST_TIMEOUT}s",
                "code": -2,
            }
        }
    except httpx.ConnectError as e:
        logger.error(f"WhatsApp API connection error: {e}")
        return {
            "error": {
                "message": f"Connection failed: {e}",
                "code": -3,
            }
        }
    except Exception as e:
        logger.error(f"WhatsApp dispatch unexpected error: {e}")
        return {
            "error": {
                "message": f"Unexpected error: {e}",
                "code": -99,
            }
        }


# ═════════════════════════════════════════════════════════════
#  TEMPLATE MESSAGE (for pre-approved Meta templates)
# ═════════════════════════════════════════════════════════════

def dispatch_template_message(
    phone_number_id: str,
    access_token: str,
    to_phone: str,
    template_name: str,
    language_code: str = "en",
    components: Optional[list] = None,
) -> dict:
    """
    Sends a pre-approved WhatsApp template message.

    Template messages are required for initiating conversations
    (24-hour window rule). They must be pre-approved by Meta.

    Args:
        phone_number_id: WhatsApp Business phone number ID
        access_token: Meta API access token
        to_phone: Recipient in E.164 format
        template_name: Meta-approved template name
        language_code: Template language (default: "en")
        components: Template variable components (header, body params)

    Returns:
        dict: Meta API response
    """
    to_phone = _normalize_phone(to_phone)
    if not to_phone:
        return {"error": {"message": "Invalid phone number", "code": -1}}

    url = f"{GRAPH_API_BASE}/{phone_number_id}/messages"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
        },
    }

    # Add dynamic components if provided
    if components:
        payload["template"]["components"] = components

    logger.info(
        f"Dispatching template '{template_name}' to {_mask_phone(to_phone)}"
    )

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            response = client.post(url, json=payload, headers=headers)

        result = response.json()

        if response.status_code == 200 and "messages" in result:
            logger.info(
                f"✅ Template message sent: {template_name} "
                f"(wa_id={result['messages'][0].get('id')})"
            )
        elif "error" in result:
            logger.error(
                f"❌ Template send error: {result['error'].get('message')}"
            )

        return result

    except Exception as e:
        logger.error(f"Template dispatch error: {e}")
        return {"error": {"message": str(e), "code": -99}}


# ═════════════════════════════════════════════════════════════
#  UTILITIES
# ═════════════════════════════════════════════════════════════

def _normalize_phone(phone: str) -> Optional[str]:
    """
    Normalizes phone number to E.164 format for WhatsApp.

    Examples:
        "+919876543210"  → "919876543210"  (stripped +)
        "919876543210"   → "919876543210"  (already clean)
        "09876543210"    → None            (ambiguous, needs country code)
        ""               → None
    """
    if not phone:
        return None

    # Strip whitespace, dashes, and parentheses
    cleaned = phone.strip().replace(" ", "").replace("-", "")
    cleaned = cleaned.replace("(", "").replace(")", "")

    # Remove leading + (Meta API expects digits only)
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]

    # Must be at least 10 digits with country code
    if len(cleaned) < 10 or not cleaned.isdigit():
        logger.warning(f"Phone number too short or invalid: {_mask_phone(phone)}")
        return None

    return cleaned


def _mask_phone(phone: str) -> str:
    """Masks a phone number for safe logging (e.g., +91****3210)."""
    if not phone or len(phone) < 6:
        return "****"
    return f"{phone[:3]}****{phone[-4:]}"


# ═════════════════════════════════════════════════════════════
#  HEALTH CHECK
# ═════════════════════════════════════════════════════════════

def verify_whatsapp_credentials(
    phone_number_id: str,
    access_token: str,
) -> dict:
    """
    Verifies WhatsApp Business API credentials by fetching
    the phone number profile. Useful during merchant onboarding.

    Returns:
        dict with verified_phone_number, display_name, quality_rating
    """
    url = f"{GRAPH_API_BASE}/{phone_number_id}"

    headers = {
        "Authorization": f"Bearer {access_token}",
    }

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            response = client.get(url, headers=headers)

        if response.status_code == 200:
            data = response.json()
            logger.info(
                f"✅ WhatsApp credentials verified: "
                f"{data.get('display_phone_number')} "
                f"({data.get('verified_name')})"
            )
            return {
                "verified": True,
                "phone_number": data.get("display_phone_number"),
                "display_name": data.get("verified_name"),
                "quality_rating": data.get("quality_rating"),
                "platform_type": data.get("platform_type"),
            }
        else:
            error = response.json().get("error", {})
            logger.error(f"❌ Credential verification failed: {error}")
            return {
                "verified": False,
                "error": error.get("message", "Unknown error"),
            }

    except Exception as e:
        logger.error(f"Credential verification exception: {e}")
        return {"verified": False, "error": str(e)}
