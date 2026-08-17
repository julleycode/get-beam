# ReTargetAgent: Product Roadmap for MVP

## Product Vision (One Sentence)
An AI agent that sits on any website via a lightweight pixel, identifies anonymous visitors, enriches their profiles across social channels, and automatically plans + drafts personalized retargeting campaigns across organic and paid touchpoints — you approve every send.

## Target User
Founders and operators of DTC (Direct to Consumer) websites, vibe coded web apps, and indie SaaS products who:
1. Have meaningful traffic but no tracking infrastructure
2. Don't want to break user flow by forcing email capture
3. Can't afford or don't want to manage Klaviyo, HubSpot, or enterprise CDPs (Customer Data Platforms)
4. Want retargeting that "just works" without hiring a growth marketer

## Core Value Proposition
"Paste one script tag. We handle everything else: identify who visited, find their social profiles, and auto-run retargeting campaigns."

## Critical Constraints for MVP
1. BUDGET: Target customer pays 49 to 199 USD per month. API costs must stay under 40% of revenue per customer.
2. ACCURACY: Identity resolution on low traffic international sites will be 5 to 15%, not 25 to 35%. Design UX around this reality. Don't overpromise.
3. COMPLIANCE: MVP ships with US market only. EU visitors get excluded by default. Add GDPR support in v2.
4. SCOPE: Ship something usable in 4 to 6 weeks. Cut anything that doesn't directly prove the core loop works.

---

## Architecture Overview

```
[Website with Pixel] 
    → [Event Collector API]
    → [Identity Resolution Pipeline]
    → [Enrichment Pipeline]  
    → [AI Segmentation Engine]
    → [Campaign Planner Agent]
    → [Activation Layer: Email / CSV Export / Organic Suggestions]
    → [Dashboard for Human Review]
```

---

## PHASE 0: Project Setup (Day 1 to 2)

### 0.1 Initialize Monorepo
```
retarget-agent/
├── apps/
│   ├── web/                  # Next.js dashboard
│   ├── api/                  # FastAPI backend
│   └── pixel/                # Vanilla JS tracking pixel
├── packages/
│   ├── shared/               # Shared types and utilities
│   └── ai/                   # AI agent logic (prompts, chains)
├── infra/
│   ├── docker-compose.yml
│   └── .env.example
├── CLAUDE.md                 # Instructions for Claude Code
├── README.md
└── package.json
```

### 0.2 Tech Stack (Locked, No Debates)
| Layer | Technology | Why |
|-------|-----------|-----|
| Frontend Dashboard | Next.js 14 (App Router) + Tailwind CSS + shadcn/ui | Fast to build, good DX, looks professional |
| Backend API | Python FastAPI | Best async support, easy to integrate ML later |
| Database (primary) | PostgreSQL (via Supabase or Neon) | Profiles, campaigns, user accounts |
| Database (events) | ClickHouse (via ClickHouse Cloud free tier) or TimescaleDB | Time series event data from pixel |
| Cache | Redis (via Upstash) | Cache enrichment results, rate limiting |
| Queue | Celery with Redis broker | Async enrichment jobs, campaign generation |
| AI | Anthropic Claude API (claude-sonnet-4-20250514) | Segmentation, campaign planning, copy generation |
| Email Sending | Resend API | Simple, cheap, good deliverability |
| Hosting | Railway (MVP) | One click deploy, cheap, scales later |
| Pixel CDN | Cloudflare Workers | Edge delivery, fast globally |

### 0.3 External API Accounts Needed (Sign Up Before Coding)
1. People Data Labs (identity resolution + enrichment): https://www.peopledatalabs.com/ (free tier: 100 records/month)
2. FullContact (identity resolution fallback): https://www.fullcontact.com/ (free tier: 100 matches/month)
3. Proxycurl (LinkedIn enrichment): https://nubela.co/proxycurl/ (free tier: 10 credits)
4. Anthropic Claude API: https://console.anthropic.com/
5. Resend (email sending): https://resend.com/ (free tier: 100 emails/day)
6. Upstash (Redis + Kafka): https://upstash.com/ (free tier available)

### 0.4 CLAUDE.md File for Claude Code
Create this file at repo root so Claude Code understands the project:

```markdown
# ReTargetAgent

## What This Is
AI-powered retargeting agent for websites. Pixel on site -> identify anonymous visitors -> enrich profiles -> AI segments them -> auto-plan retargeting campaigns.

## Tech Stack  
- Frontend: Next.js 14 + Tailwind + shadcn/ui (apps/web)
- Backend: Python FastAPI (apps/api)
- Pixel: Vanilla JS deployed to Cloudflare Workers (apps/pixel)
- DB: PostgreSQL (profiles, campaigns), ClickHouse (events)
- Cache: Redis via Upstash
- Queue: Celery + Redis
- AI: Claude API (claude-sonnet-4-20250514)
- Email: Resend API

## Key Conventions
- Python: Use type hints everywhere. Pydantic models for all API schemas.
- TypeScript: Strict mode. No `any` types.
- API: RESTful. All endpoints return JSON. Use HTTP status codes properly.
- Errors: Never swallow errors silently. Log with structured logging (structlog for Python).
- Env vars: All secrets in .env, never hardcoded. Use pydantic-settings for Python config.
- Tests: Write tests for critical paths (identity resolution pipeline, enrichment waterfall, AI segmentation).

## File Organization
- apps/api/routers/ -> API route handlers
- apps/api/services/ -> Business logic
- apps/api/models/ -> SQLAlchemy models
- apps/api/schemas/ -> Pydantic request/response schemas
- apps/api/tasks/ -> Celery async tasks
- apps/api/agents/ -> AI agent logic (prompts, chains, tool definitions)
- apps/web/app/ -> Next.js pages and layouts
- apps/web/components/ -> React components
- apps/pixel/src/ -> Tracking pixel source code

## Database Naming
- Tables: snake_case, plural (visitors, enrichment_results, campaigns)
- Columns: snake_case
- Foreign keys: {table_singular}_id
- Indexes: idx_{table}_{column}

## When Unsure
- Check existing patterns in the codebase first
- Prefer simple solutions over clever ones
- If an external API call can fail, it WILL fail. Always handle errors.
- Never store PII (Personally Identifiable Information) in logs
```

---

## PHASE 1: Tracking Pixel + Event Collection (Week 1)

This is the foundation. Nothing works without data flowing in.

### 1.1 Build the JavaScript Pixel

**File: `apps/pixel/src/tracker.js`**

Requirements:
- Total size under 5KB gzipped
- Zero dependencies (vanilla JS only)
- Must not block page rendering (load async)
- Sets a first party cookie with a unique visitor_id (UUID v4)
- Collects per pageview:
  - visitor_id (from cookie)
  - page URL and referrer
  - UTM parameters (source, medium, campaign, term, content)
  - timestamp (ISO 8601)
  - viewport width and height
  - device type (mobile/tablet/desktop, inferred from viewport)
  - browser language
- Collects behavioral signals:
  - Scroll depth (25%, 50%, 75%, 100% thresholds)
  - Time on page (ping every 15 seconds while tab is active)
  - Click events on links and buttons (capture element text + href, NOT form inputs)
  - Page visibility changes (tab focus/blur)
- Batches events and sends via navigator.sendBeacon or fetch fallback every 10 seconds or on page unload
- Endpoint: POST to `{API_BASE_URL}/api/v1/events/ingest`
- Payload format:
```json
{
  "site_id": "site_abc123",
  "visitor_id": "uuid-here",
  "events": [
    {
      "type": "pageview",
      "url": "https://example.com/pricing",
      "referrer": "https://google.com",
      "utm": {"source": "google", "medium": "cpc"},
      "viewport": {"w": 1440, "h": 900},
      "device": "desktop",
      "lang": "en-US",
      "ts": "2025-05-20T10:30:00Z"
    },
    {
      "type": "scroll",
      "depth": 75,
      "url": "https://example.com/pricing",
      "ts": "2025-05-20T10:30:45Z"
    }
  ]
}
```

**DO NOT collect:**
- Form input values (privacy risk, not needed)
- Keystrokes
- Mouse movements
- IP addresses in the pixel itself (let the server capture from request headers)

**Embed snippet for customers:**
```html
<script async src="https://pixel.retargetagent.com/t.js" data-site="SITE_ID_HERE"></script>
```

### 1.2 Event Ingestion API

**File: `apps/api/routers/events.py`**

Requirements:
- POST `/api/v1/events/ingest`
- Accept batched events from pixel
- Validate payload with Pydantic schema
- Extract IP address from request headers (X-Forwarded-For or direct)
- GeoIP lookup using MaxMind GeoLite2 free database (country + region level only)
- Store events in ClickHouse (or TimescaleDB)
- Rate limit: 1000 events per minute per site_id
- Return 204 No Content on success (pixel doesn't need response body)
- CORS headers: allow all origins (pixel runs on customer sites)

**Event storage schema (ClickHouse):**
```sql
CREATE TABLE events (
    site_id String,
    visitor_id String,
    event_type String,
    url String,
    referrer String,
    utm_source String,
    utm_medium String,
    utm_campaign String,
    country_code String,
    region String,
    device_type String,
    browser_lang String,
    scroll_depth UInt8,
    time_on_page UInt32,
    created_at DateTime
) ENGINE = MergeTree()
ORDER BY (site_id, visitor_id, created_at)
TTL created_at + INTERVAL 90 DAY;
```

### 1.3 Visitor Profile Aggregation

**File: `apps/api/services/visitor_aggregator.py`**

A background job (Celery beat, runs every hour) that aggregates raw events into visitor profiles:

**PostgreSQL schema:**
```sql
CREATE TABLE visitors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id VARCHAR(50) NOT NULL,
    visitor_id VARCHAR(100) NOT NULL,
    first_seen TIMESTAMP NOT NULL,
    last_seen TIMESTAMP NOT NULL,
    total_pageviews INTEGER DEFAULT 0,
    total_sessions INTEGER DEFAULT 0,
    avg_time_on_page FLOAT DEFAULT 0,
    max_scroll_depth INTEGER DEFAULT 0,
    pages_visited JSONB DEFAULT '[]',
    top_referrer VARCHAR(500),
    utm_source VARCHAR(200),
    utm_medium VARCHAR(200),
    country_code VARCHAR(5),
    device_type VARCHAR(20),
    intent_score FLOAT DEFAULT 0,
    identity_status VARCHAR(20) DEFAULT 'anonymous',
    enrichment_status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    UNIQUE(site_id, visitor_id)
);

CREATE INDEX idx_visitors_site_intent ON visitors(site_id, intent_score DESC);
CREATE INDEX idx_visitors_identity_status ON visitors(site_id, identity_status);
```

**Intent Score Calculation (rule based for MVP):**
```python
def calculate_intent_score(visitor_data: dict) -> float:
    score = 0.0
    
    # Recency (last seen within 24h = high intent)
    hours_since_last = (now() - visitor_data["last_seen"]).total_seconds() / 3600
    if hours_since_last < 24:
        score += 30
    elif hours_since_last < 72:
        score += 20
    elif hours_since_last < 168:  # 7 days
        score += 10
    
    # Frequency
    if visitor_data["total_sessions"] >= 3:
        score += 25
    elif visitor_data["total_sessions"] >= 2:
        score += 15
    
    # Depth
    if visitor_data["max_scroll_depth"] >= 75:
        score += 15
    if visitor_data["avg_time_on_page"] > 60:  # seconds
        score += 10
    
    # High intent pages (configurable per site)
    high_intent_keywords = ["pricing", "checkout", "signup", "demo", "contact", "buy"]
    pages = visitor_data.get("pages_visited", [])
    if any(kw in page.lower() for page in pages for kw in high_intent_keywords):
        score += 20
    
    return min(score, 100.0)
```

### 1.4 Phase 1 Deliverable Checklist
- [ ] Pixel script loads async, under 5KB gzipped
- [ ] Pixel sets first party cookie, collects pageviews + scroll + time on page
- [ ] Events flow to API endpoint and get stored
- [ ] Visitor profiles aggregate hourly with intent scores
- [ ] Can see visitor list in database with intent scores
- [ ] Basic health check: paste pixel on a test page, see events appear in DB within 30 seconds

---

## PHASE 2: Identity Resolution + Enrichment (Week 2 to 3)

### 2.1 Identity Resolution Pipeline

**File: `apps/api/services/identity_resolver.py`**

This is the most critical and most expensive part. The waterfall approach:

```
Step 1: Check if visitor already identified (cache hit in Redis)
    → If yes, skip to enrichment
    → If no, continue

Step 2: Query People Data Labs with IP + user agent + behavioral signals
    → Cost: ~0.01 to 0.05 USD per lookup
    → Expected match rate: 5 to 15% for international traffic
    → If match found, save email + name + basic demographics
    → If no match, continue

Step 3: Query FullContact as fallback
    → Cost: ~0.01 to 0.03 USD per lookup  
    → If match found, save
    → If no match, mark as "unresolvable" and don't retry for 30 days
```

**CRITICAL COST CONTROLS:**
- Only trigger resolution for visitors with intent_score >= 40 (saves 60 to 70% of API costs)
- Cache all results in Redis with 30 day TTL
- Never resolve the same visitor_id twice within 30 days
- Daily budget cap per site: configurable, default 50 lookups/day
- Track spend per site in PostgreSQL for billing

**PostgreSQL schema:**
```sql
CREATE TABLE identified_visitors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    visitor_id VARCHAR(100) NOT NULL,
    site_id VARCHAR(50) NOT NULL,
    email VARCHAR(320),
    full_name VARCHAR(200),
    phone VARCHAR(50),
    city VARCHAR(100),
    region VARCHAR(100),
    country VARCHAR(5),
    gender VARCHAR(20),
    age_range VARCHAR(20),
    resolution_provider VARCHAR(50),
    confidence_score FLOAT,
    resolved_at TIMESTAMP DEFAULT now(),
    UNIQUE(site_id, visitor_id)
);

CREATE TABLE resolution_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id VARCHAR(50) NOT NULL,
    visitor_id VARCHAR(100) NOT NULL,
    provider VARCHAR(50) NOT NULL,
    success BOOLEAN NOT NULL,
    cost_usd FLOAT NOT NULL,
    response_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT now()
);
```

### 2.2 Enrichment Pipeline

**File: `apps/api/services/enricher.py`**

Once identity is resolved (we have an email or name), enrich with social and professional data:

```
Step 1: People Data Labs Person Enrichment API
    → Input: email
    → Returns: LinkedIn URL, Twitter/X handle, job title, company, industry, interests
    → Cost: ~0.01 to 0.05 USD per lookup

Step 2: Proxycurl (LinkedIn only, for high intent visitors with intent_score >= 70)
    → Input: LinkedIn URL from Step 1
    → Returns: Full profile data, recent posts, connections count, headline
    → Cost: ~0.01 USD per lookup
    → ONLY for visitors worth the extra cost

Step 3: Twitter/X API (if handle found, for visitors with intent_score >= 60)
    → Input: Twitter handle
    → Returns: Bio, recent tweets, follower count
    → Cost: Free tier available, or ~100 USD/month for basic access
```

**PostgreSQL schema:**
```sql
CREATE TABLE enrichment_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    visitor_id VARCHAR(100) NOT NULL,
    site_id VARCHAR(50) NOT NULL,
    
    -- Professional
    job_title VARCHAR(200),
    company_name VARCHAR(200),
    company_size VARCHAR(50),
    industry VARCHAR(100),
    seniority_level VARCHAR(50),
    
    -- Social
    linkedin_url VARCHAR(500),
    twitter_handle VARCHAR(100),
    github_url VARCHAR(500),
    personal_website VARCHAR(500),
    
    -- LinkedIn Details (from Proxycurl)
    linkedin_headline VARCHAR(500),
    linkedin_summary TEXT,
    linkedin_follower_count INTEGER,
    
    -- Twitter Details
    twitter_bio VARCHAR(500),
    twitter_follower_count INTEGER,
    twitter_recent_topics JSONB DEFAULT '[]',
    
    -- Computed
    enrichment_completeness FLOAT DEFAULT 0,  -- 0 to 1, how much data we found
    enriched_at TIMESTAMP DEFAULT now(),
    
    UNIQUE(site_id, visitor_id)
);
```

**Enrichment Completeness Score:**
```python
def calculate_completeness(profile: dict) -> float:
    fields = [
        "email", "full_name", "job_title", "company_name",
        "linkedin_url", "twitter_handle", "industry"
    ]
    filled = sum(1 for f in fields if profile.get(f))
    return filled / len(fields)
```

### 2.3 Celery Task Orchestration

**File: `apps/api/tasks/resolution_tasks.py`**

```python
# Runs every hour via Celery Beat
@celery_app.task
def process_pending_visitors(site_id: str):
    """
    1. Fetch visitors with identity_status='anonymous' and intent_score >= 40
    2. Check daily budget for site
    3. Run identity resolution waterfall
    4. If resolved, trigger enrichment task
    5. Update visitor status
    """
    pass

@celery_app.task  
def enrich_resolved_visitor(visitor_id: str, site_id: str):
    """
    1. Fetch identified visitor data
    2. Run enrichment waterfall
    3. Save enrichment profile
    4. Update enrichment_status on visitor record
    5. If enrichment_completeness >= 0.5, mark as 'ready_for_segmentation'
    """
    pass
```

### 2.4 Phase 2 Deliverable Checklist
- [ ] Identity resolution waterfall works with People Data Labs + FullContact
- [ ] Cost controls: only resolve intent_score >= 40, daily budget cap, Redis caching
- [ ] Enrichment pipeline fills social profiles from resolved emails
- [ ] Resolution and enrichment logs track spend per site
- [ ] Can see enriched profiles in database with LinkedIn/Twitter data
- [ ] End to end test: visit test site → pixel fires → events stored → visitor aggregated → identity resolved → profile enriched

---

## PHASE 3: AI Segmentation Engine (Week 3 to 4)

### 3.1 AI Powered Segmentation

**File: `apps/api/agents/segmenter.py`**

This is where the AI agent adds real value. Instead of rule based segments, Claude analyzes enriched visitor cohorts and creates meaningful groups.

**Input to Claude:** Batch of enriched visitor profiles (up to 50 at a time)
**Output from Claude:** Segment assignments with reasoning

```python
SEGMENTATION_PROMPT = """
You are a growth marketing strategist analyzing website visitors for retargeting.

## Website Context
Site: {site_name}
Site Description: {site_description}
Site Category: {site_category}

## Visitor Batch (JSON)
{visitor_profiles_json}

## Your Task
Analyze these visitors and group them into 2 to 5 actionable segments. Each segment must be:
1. Large enough to be worth targeting (at least 3 visitors)
2. Distinct enough that they need different messaging
3. Actionable (you can actually reach them somewhere)

## Output Format (JSON only, no markdown)
{{
  "segments": [
    {{
      "segment_id": "seg_001",
      "name": "Short descriptive name",
      "description": "Who these people are and why they are grouped",
      "visitor_ids": ["id1", "id2"],
      "characteristics": {{
        "common_job_titles": [],
        "common_industries": [],
        "common_behaviors": [],
        "avg_intent_score": 0
      }},
      "recommended_channels": ["email", "linkedin", "twitter", "meta_ads", "google_ads"],
      "messaging_angle": "What messaging would resonate with this group",
      "priority": "high/medium/low"
    }}
  ],
  "unsegmented_visitor_ids": ["ids that dont fit any segment"],
  "reasoning": "Brief explanation of segmentation logic"
}}
"""
```

**PostgreSQL schema:**
```sql
CREATE TABLE segments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id VARCHAR(50) NOT NULL,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    characteristics JSONB DEFAULT '{}',
    recommended_channels JSONB DEFAULT '[]',
    messaging_angle TEXT,
    priority VARCHAR(20) DEFAULT 'medium',
    visitor_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE segment_members (
    segment_id UUID REFERENCES segments(id) ON DELETE CASCADE,
    visitor_id VARCHAR(100) NOT NULL,
    site_id VARCHAR(50) NOT NULL,
    assigned_at TIMESTAMP DEFAULT now(),
    PRIMARY KEY (segment_id, visitor_id)
);
```

### 3.2 Segmentation Trigger

**File: `apps/api/tasks/segmentation_tasks.py`**

```python
@celery_app.task
def run_segmentation(site_id: str):
    """
    Triggered when:
    - A site accumulates 10+ new enriched visitors since last segmentation
    - OR manually triggered by user from dashboard
    
    Steps:
    1. Fetch all visitors with enrichment_status='ready_for_segmentation'
    2. Batch into groups of 50
    3. Call Claude API with segmentation prompt
    4. Parse response, create/update segments
    5. Assign visitors to segments
    6. Trigger campaign planning for new/updated segments
    """
    pass
```

### 3.3 Phase 3 Deliverable Checklist
- [ ] Claude API call generates meaningful segments from enriched profiles
- [ ] Segments stored in DB with visitor assignments
- [ ] Segmentation runs automatically when 10+ new enriched visitors accumulate
- [ ] Can trigger segmentation manually
- [ ] Segment output includes recommended channels and messaging angles

---

## PHASE 4: Campaign Planning Agent (Week 4 to 5)

### 4.1 Campaign Planner Agent

**File: `apps/api/agents/campaign_planner.py`**

The AI agent takes segments and creates actionable campaign plans.

```python
CAMPAIGN_PLANNING_PROMPT = """
You are an expert growth marketer creating a retargeting campaign plan.

## Segment
Name: {segment_name}
Description: {segment_description}
Size: {visitor_count} people
Characteristics: {characteristics_json}
Recommended Channels: {channels}
Messaging Angle: {messaging_angle}

## Enriched Visitor Profiles in This Segment
{visitor_profiles_json}

## Available Channels
- Email (via Resend API, direct send)
- LinkedIn (organic: connection request + note, or export for LinkedIn Ads)
- Twitter/X (organic: reply/mention, or export for X Ads)
- Meta Ads (export CSV for Custom Audiences)
- Google Ads (export CSV for Customer Match)

## Your Task
Create a campaign plan with:
1. Channel priority order (which to use first, second, etc.)
2. For each channel, write the actual message/copy ready to send
3. Timing: when to send each touchpoint
4. Follow up sequence: what happens if no response after 3 days

## Output Format (JSON only, no markdown)
{{
  "campaign_name": "Descriptive campaign name",
  "segment_id": "{segment_id}",
  "total_touchpoints": 3,
  "touchpoints": [
    {{
      "order": 1,
      "channel": "email",
      "delay_hours_from_start": 0,
      "subject": "Email subject line",
      "body": "Full email body. Use {{first_name}} for personalization.",
      "personalization_fields": ["first_name", "company_name"],
      "cta": "What action you want them to take"
    }},
    {{
      "order": 2,
      "channel": "linkedin",
      "delay_hours_from_start": 48,
      "connection_note": "LinkedIn connection request note (max 300 chars)",
      "followup_message": "Message after connection accepted",
      "personalization_fields": ["first_name", "job_title"]
    }},
    {{
      "order": 3,
      "channel": "meta_ads",
      "delay_hours_from_start": 0,
      "ad_headline": "Ad headline",
      "ad_body": "Ad body copy",
      "audience_description": "How to set up the custom audience"
    }}
  ],
  "success_metric": "What defines success for this campaign",
  "estimated_reach": "Realistic estimate of how many people this will actually reach"
}}
"""
```

**PostgreSQL schema:**
```sql
CREATE TABLE campaigns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id VARCHAR(50) NOT NULL,
    segment_id UUID REFERENCES segments(id),
    name VARCHAR(200) NOT NULL,
    status VARCHAR(20) DEFAULT 'draft',  -- draft, approved, active, paused, completed
    plan JSONB NOT NULL,  -- Full campaign plan from AI
    created_at TIMESTAMP DEFAULT now(),
    approved_at TIMESTAMP,
    started_at TIMESTAMP
);

CREATE TABLE campaign_touchpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id UUID REFERENCES campaigns(id) ON DELETE CASCADE,
    visitor_id VARCHAR(100) NOT NULL,
    channel VARCHAR(50) NOT NULL,
    touchpoint_order INTEGER NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',  -- pending, sent, delivered, opened, clicked, bounced, failed
    content JSONB NOT NULL,  -- Personalized content for this specific visitor
    scheduled_at TIMESTAMP,
    sent_at TIMESTAMP,
    opened_at TIMESTAMP,
    clicked_at TIMESTAMP
);
```

### 4.2 Phase 4 Deliverable Checklist
- [ ] Claude generates multi channel campaign plans for each segment
- [ ] Plans include actual copy ready to send (email subjects, bodies, LinkedIn notes, ad copy)
- [ ] Copy is personalized with visitor profile data (name, company, job title)
- [ ] Campaign plans stored in DB with draft status
- [ ] Campaigns require human approval before activation (CRITICAL: never auto send without approval)

---

## PHASE 5: Activation Layer (Week 5)

### 5.1 Email Sending

**File: `apps/api/services/email_sender.py`**

```python
# Use Resend API
# Requirements:
# 1. Send personalized emails from campaign touchpoints
# 2. Track delivery, opens, clicks via Resend webhooks
# 3. Respect rate limits: max 50 emails per hour per site (start conservative)
# 4. Include unsubscribe link in every email (CAN SPAM compliance)
# 5. Never send to same visitor twice in 7 days
# 6. Handle bounces: mark visitor as "do_not_email" after hard bounce
```

### 5.2 CSV Export for Paid Channels

**File: `apps/api/services/csv_exporter.py`**

Export audience lists for paid ad platforms:

```python
# Meta Custom Audiences format
# Columns: email, phone, fn (first name), ln (last name), ct (city), st (state), country, zip
# Must be SHA256 hashed before upload

# Google Customer Match format  
# Columns: Email, Phone, First Name, Last Name, Country, Zip

# LinkedIn Matched Audiences format
# Columns: email (or company name + job title for company targeting)

# Each export function:
# 1. Takes a segment_id
# 2. Fetches all identified visitors in segment
# 3. Formats per platform spec
# 4. Returns downloadable CSV
# 5. Logs export event
```

### 5.3 Organic Outreach Suggestions

For LinkedIn and Twitter/X organic outreach, DO NOT auto send in MVP. Instead:

```python
# Generate a "suggested actions" list per visitor:
# {
#   "visitor_name": "John Smith",
#   "linkedin_url": "https://linkedin.com/in/johnsmith",
#   "suggested_action": "Send connection request",
#   "suggested_message": "Hey John, noticed you checked out...",
#   "twitter_handle": "@johnsmith",
#   "suggested_tweet_reply": "..."
# }
# 
# User copies message and sends manually.
# This keeps us out of LinkedIn/Twitter TOS violations.
# Automate in v2 after validating demand.
```

### 5.4 Phase 5 Deliverable Checklist
- [ ] Email sending works via Resend with personalization
- [ ] Emails include unsubscribe link
- [ ] Bounce handling marks bad emails
- [ ] CSV export works for Meta, Google, LinkedIn audience formats
- [ ] Organic suggestions generated with copy to clipboard functionality
- [ ] All activations require human approval first

---

## PHASE 6: Dashboard (Week 5 to 6)

### 6.1 Pages to Build

**Page 1: Onboarding**
- Sign up / login (use Supabase Auth or Clerk)
- Create site: enter site name + URL
- Get pixel snippet to paste on site
- Verification: check if events are flowing

**Page 2: Visitors Overview**
- Table of all visitors for selected site
- Columns: visitor_id (truncated), first seen, last seen, pageviews, intent score, identity status, enrichment status
- Filter by: identity status (anonymous / identified / enriched), intent score range, date range
- Sort by: intent score, last seen, pageviews
- Click on visitor to see full profile

**Page 3: Visitor Detail**
- Behavioral timeline (pages visited, scroll depth, time on page)
- Identity info (email, name, location) if resolved
- Enrichment data (job title, company, LinkedIn, Twitter) if enriched
- Segment memberships
- Campaign touchpoints history

**Page 4: Segments**
- List of AI generated segments
- Each shows: name, visitor count, recommended channels, priority
- Click to see members and campaign plan
- Button: "Re run segmentation" (triggers manual segmentation)

**Page 5: Campaigns**
- List of campaigns with status (draft / approved / active / completed)
- Click to see full plan with all touchpoints
- Approve button (moves from draft to approved)
- Start button (begins sending scheduled touchpoints)
- Pause button
- For each campaign: metrics (sent, delivered, opened, clicked)

**Page 6: Exports**
- Select segment
- Choose platform (Meta / Google / LinkedIn)
- Download CSV
- Export history

**Page 7: Settings**
- Site settings (pixel verification, site description for AI context)
- API usage dashboard (resolution lookups, enrichment calls, Claude API calls)
- Budget controls (daily lookup limit, monthly spend cap)
- Email settings (sender name, sender email, Resend API key or use shared)
- Billing (Stripe integration, for v2, just show usage for now)

### 6.2 Dashboard Design Direction
- Clean, data dense, professional
- Dark mode default (target audience is developers and indie makers)
- Use shadcn/ui components (Table, Card, Badge, Dialog, Sheet)
- Inspiration: PostHog dashboard, Linear, Vercel dashboard
- No flashy animations. Speed and clarity over aesthetics.
- Mobile responsive but optimize for desktop (users manage campaigns on desktop)

### 6.3 Phase 6 Deliverable Checklist
- [ ] Auth works (signup, login, logout)
- [ ] Can create site and get pixel snippet
- [ ] Pixel verification shows events flowing
- [ ] Visitors table shows data with filters and sorting
- [ ] Visitor detail page shows full profile
- [ ] Segments page shows AI generated segments
- [ ] Campaign approval and activation flow works
- [ ] CSV export downloads correct files
- [ ] Settings page has budget controls

---

## DATA FLOW: End to End Happy Path

```
1. User signs up, creates site "MyApp", gets pixel snippet
2. User pastes <script> tag on their website
3. Visitor browses MyApp's site
4. Pixel fires events → API stores in ClickHouse
5. Hourly job aggregates visitor profile in PostgreSQL (intent_score = 65)
6. Since intent_score >= 40, identity resolution triggers
7. People Data Labs matches: email = john@company.com, name = John Smith
8. Enrichment triggers: LinkedIn found, job = "CTO at StartupXYZ", Twitter found
9. After 10+ enriched visitors accumulate, segmentation triggers
10. Claude creates segment: "Technical Founders Evaluating Product" (5 visitors)
11. Claude creates campaign plan: Email first → LinkedIn follow up → Meta retargeting
12. Campaign appears as "draft" in dashboard
13. User reviews plan, edits copy if needed, clicks "Approve"
14. User clicks "Start Campaign"
15. Email touchpoint sends via Resend with personalized content
16. 48 hours later, LinkedIn suggestion appears for manual outreach
17. User exports segment to Meta CSV for retargeting ads
18. Dashboard shows: 5 emails sent, 3 opened, 1 clicked
```

---

## MVP SUCCESS CRITERIA

The MVP is "done" when this demo works end to end:

1. Install pixel on a real website with actual traffic
2. Wait 48 to 72 hours for data accumulation
3. At least 5 visitors get identified and enriched
4. AI creates at least 1 meaningful segment
5. AI generates a campaign plan with actual personalized copy
6. Send at least 1 email that gets delivered (not bounced)
7. Export at least 1 CSV that can be uploaded to Meta Ads Manager

If all 7 work, the MVP is shippable. Everything else is iteration.

---

## WHAT IS EXPLICITLY OUT OF SCOPE FOR MVP

Do NOT build these yet. They are distractions:

- Multi user accounts / team features
- GDPR consent management (US only for MVP)
- Automated LinkedIn/Twitter sending (manual + copy to clipboard only)
- Custom domain for email sending (use shared domain first)
- Advanced ML models for intent scoring (rule based is fine)
- Real time dashboard / websocket updates (polling every 30 seconds is fine)
- Mobile app
- White labeling
- Webhooks / API for customers to build on
- A/B testing of campaign copy
- Integration with Shopify, Klaviyo, Mailchimp (these are v2)
- Billing / payment processing (manual invoicing or free beta for first 10 users)
- Custom branding on emails (use simple, clean default template)

---

## RISK REGISTER

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Identity resolution match rate below 5% | High | Critical | Set expectations in onboarding. Show "identified X of Y visitors" prominently. Let users provide their own email lists to supplement. |
| API costs exceed revenue per customer | High | Critical | Aggressive intent score filtering. Daily budget caps. Monitor unit economics weekly. |
| Emails land in spam | Medium | High | Use Resend (good deliverability). Start with low volume. Warm up gradually. Include unsubscribe. |
| LinkedIn blocks scraping | Medium | Medium | Use Proxycurl (compliant API). Never auto send LinkedIn messages. |
| Customer sites have < 500 visitors/month | High | Medium | Set minimum traffic requirement in onboarding. Be honest: "This product works best with 1000+ monthly visitors." |
| Users don't approve campaigns (friction) | Medium | Medium | Make approval flow dead simple. One click approve. Show preview of exactly what will be sent. |

---

## IMPLEMENTATION ORDER FOR CLAUDE CODE

Follow this exact order. Do not skip ahead.

```
1. Project setup (monorepo, env, docker compose)
2. PostgreSQL schema (all tables)
3. ClickHouse schema (events table)
4. Pixel JavaScript
5. Event ingestion API endpoint
6. Visitor aggregation job
7. Identity resolution service (with mock/test mode)
8. Enrichment service (with mock/test mode)  
9. Celery task orchestration
10. AI segmentation agent
11. AI campaign planner agent
12. Email sending service
13. CSV export service
14. Auth (Supabase Auth or Clerk)
15. Dashboard: onboarding flow
16. Dashboard: visitors page
17. Dashboard: visitor detail page
18. Dashboard: segments page
19. Dashboard: campaigns page (with approve/start flow)
20. Dashboard: exports page
21. Dashboard: settings page
22. Integration testing: full pipeline end to end
23. Deploy to Railway
24. Pixel deploy to Cloudflare Workers
```

Each step should be a separate Claude Code session/task. Test each step before moving to the next. If a step fails, fix it before continuing.
