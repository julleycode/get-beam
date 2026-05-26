# Deployment Checklist — EasyTrack + EasyEngage Merge

## Railway Backend Environment Variables

Add these new variables to your Railway project:

### Clerk Auth
```
CLERK_SECRET_KEY=sk_live_...
CLERK_PUBLISHABLE_KEY=pk_live_...
JWT_SECRET=<existing app_secret_key value>
JWT_ALGORITHM=HS256
```

### OAuth Credentials (per platform)
```
TWITTER_CLIENT_ID=
TWITTER_CLIENT_SECRET=
TWITTER_REDIRECT_URI=https://retarget-agent-production.up.railway.app/api/v1/social/callback/twitter

FACEBOOK_APP_ID=
FACEBOOK_APP_SECRET=
FACEBOOK_REDIRECT_URI=https://retarget-agent-production.up.railway.app/api/v1/social/callback/facebook

LINKEDIN_CLIENT_ID=
LINKEDIN_CLIENT_SECRET=
LINKEDIN_REDIRECT_URI=https://retarget-agent-production.up.railway.app/api/v1/social/callback/linkedin

TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=
TIKTOK_REDIRECT_URI=https://retarget-agent-production.up.railway.app/api/v1/social/callback/tiktok
```

### Token Encryption
```
TOKEN_ENCRYPTION_KEY=<generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
```

### Feed Sync
```
SYNC_INTERVAL_MINUTES=15
```

## Vercel Frontend Environment Variables

Add to Vercel project settings:
```
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_live_...
NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in
NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up
```

## Clerk Dashboard Setup

1. Go to https://dashboard.clerk.com
2. Create application (or use existing)
3. Copy Secret Key → Railway `CLERK_SECRET_KEY`
4. Copy Publishable Key → Railway + Vercel `CLERK_PUBLISHABLE_KEY`
5. Add redirect URLs:
   - `https://retarget-agent.vercel.app/dashboard`
   - `https://retarget-agent.vercel.app/sign-in`
   - `https://retarget-agent.vercel.app/sign-up`

## OAuth App Setup (per platform)

### Twitter/X
1. Go to https://developer.twitter.com/en/portal/projects-and-apps
2. Create app → OAuth 2.0 → Confidential client
3. Redirect URI: `https://retarget-agent-production.up.railway.app/api/v1/social/callback/twitter`
4. Scopes: `tweet.read`, `tweet.write`, `users.read`, `offline.access`

### LinkedIn
1. Go to https://www.linkedin.com/developers/apps
2. Create app → Auth tab
3. Redirect URI: `https://retarget-agent-production.up.railway.app/api/v1/social/callback/linkedin`
4. Scopes: `r_liteprofile`, `w_member_social`

### Facebook/Instagram
1. Go to https://developers.facebook.com/apps
2. Create app → Add Facebook Login
3. Redirect URI: `https://retarget-agent-production.up.railway.app/api/v1/social/callback/facebook`
4. Instagram uses the same Facebook app

### TikTok
1. Go to https://developers.tiktok.com
2. Create app → Login Kit
3. Redirect URI: `https://retarget-agent-production.up.railway.app/api/v1/social/callback/tiktok`

## Database Migration

The app auto-creates new tables on startup via `Base.metadata.create_all`.
New columns on existing tables are added via inline `ALTER TABLE IF NOT EXISTS` statements.

Tables created:
- `users` (with clerk_user_id)
- `social_accounts`
- `posts`
- `messages`
- `drafts`
- `voice_examples`

Columns added:
- `campaigns.campaign_type` (VARCHAR, default 'email')
- `campaigns.platform` (VARCHAR, nullable)

## Deploy Steps

1. Push branch to GitHub: `git push origin feature/merge-social-agent`
2. Create PR and merge to main
3. Railway auto-deploys from main
4. Vercel auto-deploys from main
5. Verify: `https://retarget-agent-production.up.railway.app/health`
6. Verify new tables in DB
7. Test Clerk login flow
8. Test social account connection (start with Twitter)
