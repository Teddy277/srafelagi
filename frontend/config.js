// API base URL — set this to your Render backend URL after deployment
// Example: window.SRAFELAGI_API_BASE = "https://srafelagi-api.onrender.com";
// Leave empty ("") if frontend and API are on the same domain.
window.SRAFELAGI_API_BASE = "";

// Telegram bot username (no @) for "Sign in with Telegram".
// MUST match the real bot, and that bot's domain must be set in @BotFather (/setdomain).
window.SRAFELAGI_BOT_USERNAME = "Srafelagi1_bot";

// Google Sign-In OAuth Client ID (Web). Create one at console.cloud.google.com
// (APIs & Services -> Credentials -> OAuth client ID -> Web application) and add
// your site to "Authorized JavaScript origins". This value is public, not a secret.
// Must also be set as the GOOGLE_CLIENT_ID env var on the server (same value).
window.SRAFELAGI_GOOGLE_CLIENT_ID = "";
