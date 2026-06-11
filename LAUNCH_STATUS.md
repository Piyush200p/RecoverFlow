# RecoverFlow AI — Launch Status & Boot Guide
# ========================================================
# Last Updated: June 11, 2026

## 1. Quick Boot Command
To start the entire application stack (Docker DB + Redis + Celery worker + Cloudflare tunnel + Shopify dev server), run this command in your PowerShell terminal at the root of the workspace:
```powershell
powershell -ExecutionPolicy Bypass -File .\start-server.ps1
```

---

## 2. Current State (Tested & Working)
* **Local Test Store**: `recoverflow-dev.myshopify.com`
* **Onboarding & Spotlight**: Fixed layout bugs; the tour works perfectly via React Portals and z-index corrections.
* **Security Check**: Active. Remix calls FastAPI with `X-RecoverFlow-Secret` header validation.
* **WhatsApp Test**: Successfully verified. 
  * *Note*: If messages are not delivering, ensure the recipient phone number (e.g. `+919893347027`) has first sent a WhatsApp message (like "Hi") to the sandbox number `+1 555 640 7745` to open the 24-hour delivery session.

---

## 3. Production Deployment Plan (Post-June 14th)
1. **GitHub Visibility**: Keep repository public until **June 14, 2026**.
2. **Commit Changes**: Stage and commit all files to Git once public phase is over.
3. **Make Private**: Switch the GitHub repository visibility to **Private** in the repository Settings.
4. **Deploy**:
   * Deploy Frontend (`recover-flow`) to Vercel/Render.
   * Deploy Backend (`backend` + `docker-compose.prod.yml`) to a VPS or Render/Railway.
   * Update the production variables using `.env.production` and config file `shopify.app.production.toml`.

---

## 4. Product Roadmap & Future Channels
To expand the app's capabilities beyond WhatsApp, we plan to implement:
1. **SMS Recovery (via Twilio/Plivo)**: Allows fallback messages if the customer doesn't have WhatsApp or if the message fails to deliver.
2. **Email Recovery (via Resend/SendGrid)**: Allows building a complete three-step omnichannel sequence (e.g., Step 1: Email after 30 mins, Step 2: WhatsApp after 4 hours, Step 3: SMS with discount code after 24 hours).
## 5. Marketing & Branding Configuration
* **Approved Shopify App Store Name:** `RecoveryFloww AI: WhatsApp Recovery`
* **Future Upgrade Name:** `RecoveryFloww AI: Cart Recovery` (when SMS/Email channels are introduced)
