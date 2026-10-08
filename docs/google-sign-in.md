# Enable Google sign-in

1. Open https://console.cloud.google.com/ and select or create a project.
2. Open Google Auth Platform. Configure Branding with your app name and support email. Under Audience, choose External (or Internal for your Workspace organization). While in Testing, add your Google email as a test user.
3. Under Clients, create an OAuth client with application type **Web application**. Add this exact authorized redirect URI:

   `http://127.0.0.1:8000/auth/google/callback`

4. Copy the client ID and secret into the project `.env` file (never into chat or Git):

```dotenv
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/auth/google/callback
DASHBOARD_URL=http://127.0.0.1:8501/Run_a_Review
```

5. Restart the API. Open http://127.0.0.1:8501/Run_a_Review, click **Sign in → Continue with Google**, and select your Google account. Google returns you to the dashboard. Create a named project to save your research; use **My research projects** to reopen it.

Use `127.0.0.1` consistently for both services; cookies need the same hostname. For deployment, use HTTPS URLs on the same hostname, register the deployed callback exactly, and set both URL variables accordingly. The dashboard needs a browser-accessible API URL (`SLR_API_URL`).

The app requests only identity scopes (openid, email, profile). It stores Google's stable subject identifier, verified email and display name, and hashed expiring application tokens. Google passwords and Google access/refresh tokens are not stored. Application sessions expire after 24 hours and signing out revokes them. Reloading into a new Streamlit session may require signing in again. Previous anonymous review IDs are not automatically assigned to any account.

Setup reference: https://developers.google.com/identity/openid-connect/openid-connect
