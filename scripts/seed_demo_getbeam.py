"""Demo seed for getbeam.fyi — realistic identified/enriched visitors for the demo.

Purpose: make the dashboard demo (visitors -> detail -> segments -> campaigns ->
social) look real end-to-end WITHOUT straining belief. Beam is brand-new, so the
roster is the true ICP — AI product managers and hands-on growth marketers — plus
two notable outliers. Real people, legit companies.

SAFETY
------
These are REAL people. Some emails are synthesized (first@domain) for the AI-group
rows that came without one. To make an accidental "Send emails" click harmless,
this seed pre-creates CampaignTouchpoint rows with status="sent" for every campaign
member. send_campaign_emails() is idempotent per (campaign, visitor, email) on
status=="sent", so it SKIPS all of them instead of contacting anyone. Still run the
demo with MOCK_EXTERNAL_APIS=true for extra safety.

REVERSIBLE
----------
Visitor rows get realistic UUIDv4 visitor_ids derived deterministically from a slug
(no visible "demo" tell), so --unseed recomputes the exact ids to delete. Segments
carry characteristics["_demo_seed"]=true; campaigns carry plan["_demo_seed"]=true;
seeded social posts carry a platform_post_id prefix. Re-running wipes+reinserts.

    python -m scripts.seed_demo_getbeam --unseed --site-id beam_getbeam_fyi

USAGE
-----
    python -m scripts.seed_demo_getbeam                 # seed getbeam.fyi (auto-detect)
    python -m scripts.seed_demo_getbeam --dry-run       # detect site + print plan, no writes
    python -m scripts.seed_demo_getbeam --site-id XXX   # target a specific site_id
    python -m scripts.seed_demo_getbeam --unseed        # remove all demo rows

Run from repo root so `apps.api.*` imports resolve. Uses settings.database_url
(root .env -> prod Supabase by default).
"""

import argparse
import asyncio
import hashlib
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

import apps.api.main  # noqa: F401  — transitively registers every model on Base.metadata
from apps.api.models.database import async_session, engine
from apps.api.models.campaign import Campaign, CampaignTouchpoint
from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.event import Event
from apps.api.models.post import Post
from apps.api.models.segment import Segment, SegmentMember
from apps.api.models.site import Site
from apps.api.models.social_account import Platform, SocialAccount
from apps.api.models.user import User
from apps.api.models.visitor import IdentifiedVisitor, Visitor

NOW = datetime.utcnow()
_LEGACY_PREFIX = "beamdemo_"  # earlier seed used this visible prefix; wipe still catches it
_FEED_ACCT_MARKER = "beamdemo_feed"
_POST_MARKER = "beamseed_"  # platform_post_id prefix -> lets --unseed find seeded posts


def _demo_vid(slug: str) -> str:
    """Deterministic UUIDv4-format id for a demo visitor.

    Looks exactly like a real pixel visitor_id (no tell-tale prefix), yet is
    reproducible from the slug so --unseed can recompute and delete the exact rows.
    """
    digest = hashlib.sha256(f"beamseed:v1:{slug}".encode()).digest()[:16]
    return str(uuid.UUID(bytes=digest, version=4))


# --------------------------------------------------------------------------- #
# Lead data. seg: "AI" (product/eng leaders) or "GM" (growth marketers).
# --------------------------------------------------------------------------- #
# fmt: off
LEADS = [
    # --- Kept notables (plausible outliers) ---------------------------------
    {
        "slug": "vartika_kashyap", "first": "Vartika", "full": "Vartika Kashyap", "seg": "GM",
        "email": "vartika@proofhub.com", "title": "Chief Marketing Officer", "company": "ProofHub",
        "domain": "proofhub.com", "industry": "SaaS / Productivity", "size": "51-200",
        "city": "Chandigarh", "region": "Chandigarh", "country": "IN",
        "li": "https://www.linkedin.com/in/vartika-kashyap-30653245/", "li_vanity": "vartika-kashyap-30653245",
        "tw": "Vartika", "li_followers": 300000, "tw_followers": 32000,
        "tw_bio": "CMO @ ProofHub. Writing about leadership, marketing & productivity.",
        "tw_topics": ["marketing", "leadership", "productivity", "SaaS"],
        "seniority": "executive", "completeness": 0.9,
        "summary": "Award-winning marketing leader; drives ProofHub's brand and demand as CMO.",
        "notes": "A widely-followed marketing voice and decision-maker — a power user of growth tooling.",
        "intent": 85, "pages": ["/", "/pricing", "/features", "/blog", "/case-studies"],
    },
    {
        "slug": "rakesh_gohel", "first": "Rakesh", "full": "Rakesh Gohel", "seg": "AI",
        "email": "rakesh@juteq.ca", "title": "Founder & Chief AI Strategist", "company": "JUTEQ Inc",
        "domain": "juteq.ca", "industry": "AI & Cloud Consulting", "size": "1-10",
        "city": "Toronto", "region": "Ontario", "country": "CA",
        "li": "https://www.linkedin.com/in/rakeshgohel01/", "li_vanity": "rakeshgohel01",
        "tw": "rakeshgohel01", "li_followers": 60000, "tw_followers": 9000,
        "tw_bio": "Agentic AI & cloud. Helping teams ship AI that works. Founder @ JUTEQ.",
        "tw_topics": ["agentic AI", "cloud", "LLMs", "AI strategy"],
        "seniority": "executive", "completeness": 0.9,
        "summary": "Focuses on agentic AI and cloud; advises teams on shipping production AI.",
        "notes": "An AI strategist and builder — evaluates identity/enrichment APIs for agent workflows.",
        "intent": 80, "pages": ["/", "/docs", "/features", "/integrations", "/pricing"],
    },
    # --- AI Product & Engineering leaders -----------------------------------
    {
        "slug": "greg_felice", "first": "Greg", "full": "Greg Felice", "seg": "AI",
        "email": "greg@arcova.com", "title": "Director of AI Product & Engineering", "company": "Arcova",
        "domain": "arcova.com", "industry": "Cybersecurity / AI", "size": "51-200",
        "city": "New York", "region": "New York", "country": "US",
        "li": "https://www.linkedin.com/in/gregfelice/", "li_vanity": "gregfelice",
        "tw": None, "li_followers": None, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "director", "completeness": 0.66,
        "summary": "Leads AI product and engineering at Arcova (formerly MorganFranklin Cyber); ships AI-driven security and data products.",
        "notes": "A senior AI product leader — the buyer who evaluates identity/enrichment APIs for an AI roadmap.",
        "intent": 82, "pages": ["/", "/docs", "/integrations", "/pricing"],
    },
    {
        "slug": "radhika_khandelwal", "first": "Radhika", "full": "Radhika Khandelwal", "seg": "AI",
        "email": "radhika@wand.ai", "title": "AI Product Lead", "company": "Wand AI",
        "domain": "wand.ai", "industry": "AI & Machine Learning", "size": "11-50",
        "city": "New York", "region": "New York", "country": "US",
        "li": "https://www.linkedin.com/in/radhikaakhandelwal/", "li_vanity": "radhikaakhandelwal",
        "tw": None, "li_followers": None, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "lead", "completeness": 0.6,
        "summary": "AI Product Lead at Wand AI, building enterprise AI-agent products.",
        "notes": "Owns AI product at a fast-moving startup — assessing identity data for agent workflows.",
        "intent": 74, "pages": ["/", "/features", "/docs", "/pricing"],
    },
    {
        "slug": "abhishek_gore", "first": "Abhishek", "full": "Abhishek Gore", "seg": "AI",
        "email": "abhishek@nvidia.com", "title": "Product Manager - AI Agents", "company": "NVIDIA",
        "domain": "nvidia.com", "industry": "Semiconductors / AI", "size": "10000+",
        "city": None, "region": None, "country": "US",
        "li": "https://www.linkedin.com/in/gore-abhishek/", "li_vanity": "gore-abhishek",
        "tw": None, "li_followers": None, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "manager", "completeness": 0.58,
        "summary": "Product Manager for AI Agents at NVIDIA.",
        "notes": "PM on AI agents at NVIDIA — researching identity/enrichment building blocks.",
        "intent": 70, "pages": ["/", "/docs", "/integrations"],
    },
    {
        "slug": "manasi_deshmukh", "first": "Manasi", "full": "Manasi Deshmukh", "seg": "AI",
        "email": "manasi@sikka.ai", "title": "AI Product Manager", "company": "Sikka.ai",
        "domain": "sikka.ai", "industry": "AI / Healthcare", "size": "51-200",
        "city": "San Francisco", "region": "California", "country": "US",
        "li": "https://www.linkedin.com/in/manasideshmukh-/", "li_vanity": "manasideshmukh-",
        "tw": None, "li_followers": None, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "manager", "completeness": 0.58,
        "summary": "AI Product Manager at Sikka.ai, working on AI for healthcare data.",
        "notes": "AI PM in healthcare data — evaluating enrichment/identity sources.",
        "intent": 66, "pages": ["/", "/features", "/pricing", "/docs"],
    },
    # --- Growth Marketing team ----------------------------------------------
    {
        "slug": "lina_a", "first": "Lina", "full": "Lina A.", "seg": "GM",
        "email": "lina@hingehealth.com", "title": "Growth Marketing Operations Associate", "company": "Hinge Health",
        "domain": "hingehealth.com", "industry": "Digital Health", "size": "1000-5000",
        "city": None, "region": None, "country": "US",
        "li": "https://www.linkedin.com/in/lina-a-139b35127/", "li_vanity": "lina-a-139b35127",
        "tw": None, "li_followers": 764, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "associate", "completeness": 0.86,
        "summary": "Data-driven marketer with over 4 years of experience and a deep understanding of marketing operations. Cultivated a wide variety of skills in startup environments. Passionate about creating meaningful user experiences and creative solutions.",
        "notes": "Hands-on growth-ops marketer — exactly who trials a retargeting/lead-gen tool day to day.",
        "intent": 61, "pages": ["/", "/pricing", "/features", "/integrations"],
    },
    {
        "slug": "erika_marietta", "first": "Erika", "full": "Erika Marietta, MS", "seg": "GM",
        "email": "erika@creditkarma.com", "title": "Growth Marketing Associate II", "company": "Credit Karma",
        "domain": "creditkarma.com", "industry": "FinTech", "size": "1000-5000",
        "city": "Charlotte", "region": "North Carolina", "country": "US",
        "li": "https://www.linkedin.com/in/erikamarietta/", "li_vanity": "erikamarietta",
        "tw": None, "li_followers": 773, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "associate", "completeness": 0.85,
        "summary": "Marketer who turns curiosity into actionable strategy — understands members, uncovers insights, and translates them into creative, measurable campaigns with analytical rigor and a human-first mindset.",
        "notes": "Growth marketer and campaign strategist — core ICP evaluating pipeline tooling.",
        "intent": 57, "pages": ["/", "/pricing", "/case-studies"],
    },
    {
        "slug": "kayleigh_stevens", "first": "Kayleigh", "full": "Kayleigh Stevens", "seg": "GM",
        "email": "kayleigh@simbiosys.com", "title": "Growth Marketing Associate & Account Executive", "company": "SimBioSys",
        "domain": "simbiosys.com", "industry": "MedTech / AI", "size": "11-50",
        "city": "Westford", "region": "Massachusetts", "country": "US",
        "li": "https://www.linkedin.com/in/kayleighmstevens/", "li_vanity": "kayleighmstevens",
        "tw": None, "li_followers": 762, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "associate", "completeness": 0.84,
        "summary": "Growth Marketing Associate & Account Executive at SimBioSys (MedTech, AI, Oncology). Creative thinker with hands-on digital and social marketing experience; strong grounding in human behavior.",
        "notes": "Growth + sales associate at a MedTech AI startup — hands-on evaluator of outbound tools.",
        "intent": 55, "pages": ["/", "/pricing", "/features"],
    },
    {
        "slug": "neha_tripathi", "first": "Neha", "full": "Neha Tripathi", "seg": "GM",
        "email": "neha@saksglobal.com", "title": "Digital Marketing Coordinator, Growth Marketing", "company": "Saks",
        "domain": "saksglobal.com", "industry": "Retail / Luxury", "size": "5000+",
        "city": "New York", "region": "New York", "country": "US",
        "li": "https://www.linkedin.com/in/neha-tripathi/", "li_vanity": "neha-tripathi",
        "tw": None, "li_followers": 762, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "coordinator", "completeness": 0.82,
        "summary": "Digital marketing professional with 4+ years in campaign coordination, media planning, and client-facing communication across fashion, luxury, and media.",
        "notes": "Digital/growth marketing coordinator at a luxury retailer — runs the campaigns a tool like Beam feeds.",
        "intent": 63, "pages": ["/", "/pricing", "/features", "/case-studies"],
    },
    # --- Owner (real send target on camera: only lead with do_not_email=False
    # in live mode — pressing "Send emails" delivers ONLY to this inbox) -------
    {
        "slug": "thai_tran", "first": "Thai", "full": "Thai Tran", "seg": "GM",
        "email": "tranthai.work@gmail.com", "title": "Founder", "company": "Julley",
        "domain": "julley.co", "industry": "SaaS / Growth", "size": "1-10",
        "city": "Ho Chi Minh City", "region": "Ho Chi Minh", "country": "VN",
        "li": "https://www.linkedin.com/in/julleycode/", "li_vanity": "julleycode",
        "tw": None, "li_followers": None, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "executive", "completeness": 0.72,
        "summary": "Indie SaaS founder focused on growth tooling and go-to-market experiments.",
        "notes": "Hands-on founder-marketer evaluating growth tooling — visited pricing repeatedly across sessions.",
        "intent": 87, "pages": ["/", "/pricing", "/features", "/integrations"],
    },
    {
        "slug": "mae_jauch", "first": "Mae", "full": "Mae Jauch", "seg": "GM",
        "email": "mae@mindgrasp.ai", "title": "Marketing Growth Specialist I", "company": "Mindgrasp",
        "domain": "mindgrasp.ai", "industry": "EdTech / AI", "size": "11-50",
        "city": "Orchard Park", "region": "New York", "country": "US",
        "li": "https://www.linkedin.com/in/mae-jauch-a5464a272/", "li_vanity": "mae-jauch-a5464a272",
        "tw": None, "li_followers": 745, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "specialist", "completeness": 0.87,
        "summary": "Marketing Growth Specialist with 3+ years driving data-backed UGC campaigns and performance content in fast-paced EdTech; helped scale Mindgrasp from $5M to $8M ARR in 6 months and drove 30M+ views in a month.",
        "notes": "High-output growth specialist at an AI EdTech scale-up — the daily driver of retargeting workflows.",
        "intent": 68, "pages": ["/", "/pricing", "/features", "/integrations", "/blog"],
    },
    # --- Growth marketing roster (batch 2) ----------------------------------
    {
        "slug": "kate_rubich", "first": "Kate", "full": "Kate Rubich", "seg": "GM",
        "email": "kate@thesak.com", "title": "Performance Marketing and Social Content Associate", "company": "The Sak",
        "domain": "thesak.com", "industry": "Retail / Fashion", "size": "201-500",
        "city": "Riverside", "region": "Connecticut", "country": "US",
        "li": "https://www.linkedin.com/in/kate-rubich-72b453275/", "li_vanity": "kate-rubich-72b453275",
        "tw": None, "li_followers": 787, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "associate", "completeness": 0.83,
        "summary": "Economics and Environmental Studies background applied to performance marketing and social content; strong in dataset organization, visualization and econometric analysis.",
        "notes": "Performance marketer at a DTC fashion brand — hands-on with paid and social attribution.",
        "intent": 56, "pages": ["/", "/pricing", "/features"],
    },
    {
        "slug": "julia_an", "first": "Julia", "full": "Julia An", "seg": "GM",
        "email": "julia@zynga.com", "title": "User Acquisition Associate", "company": "Zynga",
        "domain": "zynga.com", "industry": "Gaming", "size": "1000-5000",
        "city": "San Francisco", "region": "California", "country": "US",
        "li": "https://www.linkedin.com/in/julia-an-b456a81b2/", "li_vanity": "julia-an-b456a81b2",
        "tw": None, "li_followers": 863, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "associate", "completeness": 0.84,
        "summary": "UC Berkeley graduate in Cognitive Science with a Data Science minor, previously at Roblox; works at the crossroads of technology, business and human-centered design.",
        "notes": "User-acquisition associate at a large gaming publisher — buys and measures traffic daily.",
        "intent": 60, "pages": ["/", "/pricing", "/integrations"],
    },
    {
        "slug": "grace_martin", "first": "Grace", "full": "Grace Martin", "seg": "GM",
        "email": "grace@prelim.com", "title": "Growth Marketing Associate", "company": "Prelim",
        "domain": "prelim.com", "industry": "FinTech / Banking Software", "size": "11-50",
        "city": "Seattle", "region": "Washington", "country": "US",
        "li": "https://www.linkedin.com/in/grace-martin-050657244/", "li_vanity": "grace-martin-050657244",
        "tw": None, "li_followers": 915, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "associate", "completeness": 0.83,
        "summary": "University of Washington graduate with experience across marketing, client support and operations — website launches, campaign development and performance analysis.",
        "notes": "Growth marketer at a small FinTech — the kind of team that buys tooling rather than builds it.",
        "intent": 64, "pages": ["/", "/pricing", "/features", "/case-studies"],
    },
    {
        "slug": "jessica_huffman", "first": "Jessica", "full": "Jessica Huffman", "seg": "GM",
        "email": "jessica@creditkarma.com", "title": "Growth Marketing Associate II", "company": "Credit Karma",
        "domain": "creditkarma.com", "industry": "FinTech", "size": "1000-5000",
        "city": "Charlotte", "region": "North Carolina", "country": "US",
        "li": "https://www.linkedin.com/in/jessica-huffman-1b632b149/", "li_vanity": "jessica-huffman-1b632b149",
        "tw": None, "li_followers": 862, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "associate", "completeness": 0.85,
        "summary": "Project manager turned growth marketer; Duke Master of Engineering Management and Six Sigma certified, with omni-channel e-commerce and retention experience.",
        "notes": "Second growth marketer on the same Credit Karma team as Erika Marietta — a real account-level signal.",
        "intent": 62, "pages": ["/", "/pricing", "/case-studies", "/features"],
    },
    {
        "slug": "rafael_granados", "first": "Rafael", "full": "Rafael Granados", "seg": "GM",
        "email": "rafael@brivo.com", "title": "Growth Marketing Associate", "company": "Brivo",
        "domain": "brivo.com", "industry": "Security / IoT SaaS", "size": "201-500",
        "city": "Austin", "region": "Texas", "country": "US",
        "li": "https://www.linkedin.com/in/rafael-granados-4ba138175/", "li_vanity": "rafael-granados-4ba138175",
        "tw": None, "li_followers": 967, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "associate", "completeness": 0.82,
        "summary": "Marketing, sales and program coordination background focused on account capture acquisition and brand experience alignment across non-profit and for-profit sectors.",
        "notes": "Runs acquisition campaigns at a B2B SaaS — direct fit for anonymous-traffic identification.",
        "intent": 66, "pages": ["/", "/pricing", "/features", "/integrations"],
    },
    {
        "slug": "kacy_mastrangelo", "first": "Kacy", "full": "Kacy Mastrangelo", "seg": "GM",
        "email": "kacy@urbanstems.com", "title": "Performance Marketing Content Associate", "company": "UrbanStems",
        "domain": "urbanstems.com", "industry": "E-commerce / DTC", "size": "51-200",
        "city": None, "region": None, "country": "US",
        "li": "https://www.linkedin.com/in/kacy-mastrangelo-58921b1a6/", "li_vanity": "kacy-mastrangelo-58921b1a6",
        "tw": None, "li_followers": 991, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "associate", "completeness": 0.62,
        "summary": "Performance marketing content associate at UrbanStems, a DTC flower and gifting brand.",
        "notes": "Performance-content marketer at a DTC brand — retargeting is the core job.",
        "intent": 58, "pages": ["/", "/pricing", "/features"],
    },
    {
        "slug": "fabiana_deluca", "first": "Fabiana", "full": "Fabiana DeLuca", "seg": "GM",
        "email": "fabiana@superbolt.agency", "title": "Junior Growth Marketing Associate", "company": "Superbolt",
        "domain": "superbolt.agency", "industry": "Marketing Agency", "size": "51-200",
        "city": "East Rockaway", "region": "New York", "country": "US",
        "li": "https://www.linkedin.com/in/fabiana-deluca-87398b20b/", "li_vanity": "fabiana-deluca-87398b20b",
        "tw": None, "li_followers": 1069, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "associate", "completeness": 0.84,
        "summary": "University of Delaware Marketing and Management graduate with sales internship experience in CRM, strategic outreach and data analysis; interested in analytics-driven merchandising.",
        "notes": "Junior growth marketer at a DTC agency — agencies evaluate tools across many client accounts.",
        "intent": 54, "pages": ["/", "/pricing", "/features"],
    },
    {
        "slug": "keith_schmelter", "first": "Keith", "full": "Keith Schmelter", "seg": "GM",
        "email": "keith@hubspot.com", "title": "Assistant Inbound Growth Specialist", "company": "HubSpot",
        "domain": "hubspot.com", "industry": "SaaS / CRM", "size": "5000+",
        "city": "Boston", "region": "Massachusetts", "country": "US",
        "li": "https://www.linkedin.com/in/keithschmelter/", "li_vanity": "keithschmelter",
        "tw": None, "li_followers": 1115, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "specialist", "completeness": 0.85,
        "summary": "Business development professional with an editorial leadership and digital content background; drives pipeline growth and outreach at HubSpot, recognised for prospecting and quota attainment.",
        "notes": "Inbound growth specialist at HubSpot — evaluating how visitor identification complements a CRM.",
        "intent": 72, "pages": ["/", "/integrations", "/pricing", "/features"],
    },
    {
        "slug": "charlotte_chute", "first": "Charlotte", "full": "Charlotte Chute", "seg": "GM",
        "email": "charlotte@dtco.ai", "title": "Growth Marketing Associate", "company": "DTCo",
        "domain": "dtco.ai", "industry": "Marketing Agency / DTC", "size": "11-50",
        "city": "Minneapolis", "region": "Minnesota", "country": "US",
        "li": "https://www.linkedin.com/in/charlottechute/", "li_vanity": "charlottechute",
        "tw": None, "li_followers": 1180, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "associate", "completeness": 0.8,
        "summary": "Creative and analytical marketer scaling e-commerce and DTC brands through performance marketing, creative strategy and data-driven testing to improve ROI on paid social and search.",
        "notes": "Agency-side growth marketer — a single win here can pull several client accounts.",
        "intent": 69, "pages": ["/", "/pricing", "/case-studies", "/features"],
    },
    {
        "slug": "paige_sponauer", "first": "Paige", "full": "Paige Sponauer", "seg": "GM",
        "email": "paige@hearst.com", "title": "Performance Marketing Associate", "company": "Hearst Magazines",
        "domain": "hearst.com", "industry": "Media / Publishing", "size": "5000+",
        "city": "New York", "region": "New York", "country": "US",
        "li": "https://www.linkedin.com/in/paige-sponauer-3896531b3/", "li_vanity": "paige-sponauer-3896531b3",
        "tw": None, "li_followers": 1205, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "associate", "completeness": 0.6,
        "summary": "Performance marketing associate at Hearst Magazines.",
        "notes": "Performance marketer at a major publisher — high-traffic site, high anonymous-visitor volume.",
        "intent": 53, "pages": ["/", "/pricing"],
    },
    {
        "slug": "alexander_schmidt", "first": "Alexander", "full": "Alexander Schmidt", "seg": "GM",
        "email": "alexander@greensky.com", "title": "Client Growth Manager, Emerging Markets", "company": "GreenSky",
        "domain": "greensky.com", "industry": "FinTech / Lending", "size": "1000-5000",
        "city": "Atlanta", "region": "Georgia", "country": "US",
        "li": "https://www.linkedin.com/in/aj-schmidt-1b40084a/", "li_vanity": "aj-schmidt-1b40084a",
        "tw": None, "li_followers": 1127, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "manager", "completeness": 0.8,
        "summary": "Business developer and sales professional across healthcare, recruiting and home improvement; skilled in sales, business development, negotiation and networking.",
        "notes": "Client growth manager — owns a book of business, cares about named-lead quality over volume.",
        "intent": 65, "pages": ["/", "/pricing", "/case-studies"],
    },
    {
        "slug": "victoria_tejeira_pinel", "first": "Victoria", "full": "Victoria Tejeira Pinel", "seg": "GM",
        "email": "victoria@ilmakiage.com", "title": "Junior Growth Marketing Manager", "company": "IL MAKIAGE",
        "domain": "ilmakiage.com", "industry": "Beauty / DTC", "size": "501-1000",
        "city": "New York", "region": "New York", "country": "US",
        "li": "https://www.linkedin.com/in/victoriatejeirapinel/", "li_vanity": "victoriatejeirapinel",
        "tw": None, "li_followers": 1209, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "manager", "completeness": 0.6,
        "summary": "Junior Growth Marketing Manager at IL MAKIAGE, a direct-to-consumer beauty brand.",
        "notes": "Growth manager at a high-spend DTC beauty brand — paid retargeting is a core budget line.",
        "intent": 67, "pages": ["/", "/pricing", "/features", "/integrations"],
    },
    {
        "slug": "hunter_budrewicz", "first": "Hunter", "full": "Hunter Budrewicz", "seg": "GM",
        "email": "hunter@converse.com", "title": "Performance Marketing Specialist 2", "company": "Converse",
        "domain": "converse.com", "industry": "Retail / Footwear", "size": "5000+",
        "city": "Southampton", "region": "Massachusetts", "country": "US",
        "li": "https://www.linkedin.com/in/hunter-budrewicz-90735214a/", "li_vanity": "hunter-budrewicz-90735214a",
        "tw": None, "li_followers": 1251, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "specialist", "completeness": 0.78,
        "summary": "Isenberg School of Management graduate focused on brand marketing; twice named to the National Way Up Top 100 Interns list.",
        "notes": "Performance marketing specialist at a global footwear brand.",
        "intent": 55, "pages": ["/", "/pricing", "/features"],
    },
    {
        "slug": "tiffany_clark", "first": "Tiffany", "full": "Tiffany Clark", "seg": "GM",
        "email": "tiffany@biziq.com", "title": "Account Manager / Growth Specialist, Digital Marketing & SEO", "company": "BizIQ",
        "domain": "biziq.com", "industry": "Marketing Agency / SEO", "size": "201-500",
        "city": "Wilmington", "region": None, "country": "US",
        "li": "https://www.linkedin.com/in/taclark22/", "li_vanity": "taclark22",
        "tw": None, "li_followers": 1264, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "manager", "completeness": 0.79,
        "summary": "Project Management and Agile certified coordinator specialising in localization and trans-national marketing of film, television and print media.",
        "notes": "Agency account manager running SEO and digital for SMB clients — multi-account evaluator.",
        "intent": 59, "pages": ["/", "/pricing", "/case-studies"],
    },
    {
        "slug": "krishna_bheda", "first": "Krishna", "full": "Krishna Bheda", "seg": "GM",
        "email": "krishna@minted.com", "title": "Growth Marketing Associate, Affiliate Marketing", "company": "Minted",
        "domain": "minted.com", "industry": "E-commerce / DTC", "size": "501-1000",
        "city": "San Francisco", "region": "California", "country": "US",
        "li": "https://www.linkedin.com/in/krishnabheda/", "li_vanity": "krishnabheda",
        "tw": None, "li_followers": 1077, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "associate", "completeness": 0.6,
        "summary": "Growth marketing and partnerships specialist focused on affiliate marketing at Minted.",
        "notes": "Affiliate and partnerships marketer — attribution and identity resolution are daily concerns.",
        "intent": 61, "pages": ["/", "/integrations", "/pricing"],
    },
    {
        "slug": "kristin_monroe", "first": "Kristin", "full": "Kristin Monroe", "seg": "GM",
        "email": "kristin@tractive.com", "title": "Growth Marketing Associate", "company": "Tractive",
        "domain": "tractive.com", "industry": "Pet Tech / IoT", "size": "201-500",
        "city": "Edmonds", "region": "Washington", "country": "US",
        "li": "https://www.linkedin.com/in/kristin-monroe-b51b0454/", "li_vanity": "kristin-monroe-b51b0454",
        "tw": None, "li_followers": 1188, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "associate", "completeness": 0.81,
        "summary": "Results-driven marketer experienced in launching advertising campaigns, maintaining client relationships, running comprehensive email campaigns and managing paid and organic social.",
        "notes": "Owns email plus paid social at a consumer IoT brand — direct fit for identified-visitor outreach.",
        "intent": 63, "pages": ["/", "/pricing", "/features", "/integrations"],
    },
    {
        "slug": "sofia_paglia", "first": "Sofia", "full": "Sofia Paglia", "seg": "GM",
        "email": "sofia@nutrafol.com", "title": "Growth Marketing Associate", "company": "Nutrafol",
        "domain": "nutrafol.com", "industry": "Health & Wellness / DTC", "size": "201-500",
        "city": "San Diego", "region": "California", "country": "US",
        "li": "https://www.linkedin.com/in/sofia-paglia-371696140/", "li_vanity": "sofia-paglia-371696140",
        "tw": None, "li_followers": 1139, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "associate", "completeness": 0.6,
        "summary": "Growth marketing associate at Nutrafol, a DTC hair-wellness brand.",
        "notes": "Growth marketer at a high-growth DTC wellness brand.",
        "intent": 57, "pages": ["/", "/pricing", "/features"],
    },
    {
        "slug": "alexia_neilas", "first": "Alexia", "full": "Alexia Neilas", "seg": "GM",
        "email": "alexia@fanduel.com", "title": "Customer Growth Associate", "company": "FanDuel",
        "domain": "fanduel.com", "industry": "Gaming / Sports Betting", "size": "1000-5000",
        "city": "New York", "region": "New York", "country": "US",
        "li": "https://www.linkedin.com/in/alexia-neilas/", "li_vanity": "alexia-neilas",
        "tw": None, "li_followers": 1067, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "associate", "completeness": 0.84,
        "summary": "Marketing professional across content strategy, partnerships support, CRM and campaign execution, with a finance and enterprise operations foundation.",
        "notes": "Customer growth associate owning CRM workflows — the person who'd wire Beam into lifecycle campaigns.",
        "intent": 64, "pages": ["/", "/integrations", "/pricing", "/features"],
    },
    {
        "slug": "gwyneth_chan", "first": "Gwyneth", "full": "Gwyneth Chan", "seg": "GM",
        "email": "gwyneth@superbolt.agency", "title": "Growth Marketing Associate", "company": "Superbolt",
        "domain": "superbolt.agency", "industry": "Marketing Agency", "size": "51-200",
        "city": "New York", "region": "New York", "country": "US",
        "li": "https://www.linkedin.com/in/gwyneth-chan-/", "li_vanity": "gwyneth-chan-",
        "tw": None, "li_followers": 1156, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "associate", "completeness": 0.6,
        "summary": "SEM and paid social analyst working across growth marketing engagements.",
        "notes": "Second Superbolt marketer in the roster — an account-level cluster, not a lone visitor.",
        "intent": 58, "pages": ["/", "/pricing", "/features"],
    },
    {
        "slug": "chloe_min", "first": "Chloe", "full": "Chloe Min", "seg": "GM",
        "email": "chloe@noom.com", "title": "Growth Marketing Associate", "company": "Noom",
        "domain": "noom.com", "industry": "Digital Health", "size": "1000-5000",
        "city": "New York", "region": "New York", "country": "US",
        "li": "https://www.linkedin.com/in/chloe-min/", "li_vanity": "chloe-min",
        "tw": None, "li_followers": 1150, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "associate", "completeness": 0.86,
        "summary": "Paid-social growth marketer managing multi-channel campaigns across Meta, Snapchat, Pinterest and TikTok for health and beauty brands; has overseen $2M+ monthly budgets and built testing roadmaps.",
        "notes": "Manages seven-figure monthly paid budgets — the highest-leverage growth buyer in the GM segment.",
        "intent": 76, "pages": ["/", "/pricing", "/features", "/case-studies", "/integrations"],
    },
    {
        "slug": "andrew_demboski", "first": "Andrew", "full": "Andrew Demboski", "seg": "GM",
        "email": "andrew@thehwpgroup.com", "title": "Growth & Marketing Associate", "company": "The HWP Group",
        "domain": "thehwpgroup.com", "industry": "Healthcare Marketing", "size": "201-500",
        "city": "New York", "region": "New York", "country": "US",
        "li": "https://www.linkedin.com/in/andrew-demboski/", "li_vanity": "andrew-demboski",
        "tw": None, "li_followers": 1130, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "associate", "completeness": 0.79,
        "summary": "Sales and marketing background in the healthcare and pharmaceutical industry; strategic thinker focused on strategies that improve patient outcomes.",
        "notes": "Growth associate at a healthcare marketing group — privacy-sensitive buyer, will read the compliance page.",
        "intent": 52, "pages": ["/", "/pricing", "/privacy"],
    },
    {
        "slug": "huy_nguyen", "first": "Huy", "full": "Huy Nguyen", "seg": "GM",
        "email": "huy@waketech.edu", "title": "Business Associate / Digital Marketer", "company": "Wake Technical Community College",
        "domain": "waketech.edu", "industry": "Education", "size": "1000-5000",
        "city": "Raleigh", "region": "North Carolina", "country": "US",
        "li": "https://www.linkedin.com/in/huy-nguyen-5b23601b2/", "li_vanity": "huy-nguyen-5b23601b2",
        "tw": None, "li_followers": 1113, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "associate", "completeness": 0.7,
        "summary": "Business associate and digital marketer currently studying at Wake Technical Community College.",
        "notes": "Early-career digital marketer — browsing rather than buying; low intent by design.",
        "intent": 34, "pages": ["/", "/pricing"],
    },
    {
        "slug": "natalie_reesor", "first": "Natalie", "full": "Natalie Reesor", "seg": "GM",
        "email": "natalie@aprio.com", "title": "Growth & Marketing Operations Associate", "company": "Aprio",
        "domain": "aprio.com", "industry": "Accounting / Advisory", "size": "1000-5000",
        "city": "Beaverton", "region": "Oregon", "country": "US",
        "li": "https://www.linkedin.com/in/nataliereesor/", "li_vanity": "nataliereesor",
        "tw": None, "li_followers": 1103, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "associate", "completeness": 0.84,
        "summary": "Marketing and operations professional supporting e-commerce, digital marketing, client services and internal operations; experienced in content creation, project coordination and data management.",
        "notes": "Marketing-ops associate — the person who actually installs and maintains the pixel.",
        "intent": 60, "pages": ["/", "/integrations", "/docs", "/pricing"],
    },
    {
        "slug": "joshua_james_ford", "first": "Joshua", "full": "Joshua James Ford", "seg": "GM",
        "email": "joshua@sellerslaunch.com", "title": "E-Commerce Growth Strategist", "company": "Sellers Launch LLC",
        "domain": "sellerslaunch.com", "industry": "E-commerce Agency", "size": "11-50",
        "city": "Indianapolis", "region": "Indiana", "country": "US",
        "li": "https://www.linkedin.com/in/joshuajamesford/", "li_vanity": "joshuajamesford",
        "tw": None, "li_followers": 1007, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "lead", "completeness": 0.85,
        "summary": "E-commerce growth strategist with a decade in direct-response advertising; specialises in SEO, PPC and conversion rate optimisation across multichannel campaigns.",
        "notes": "Runs growth for multiple e-commerce clients — an agency multiplier account.",
        "intent": 73, "pages": ["/", "/pricing", "/case-studies", "/features", "/integrations"],
    },
    {
        "slug": "giselle_barough", "first": "Giselle", "full": "Giselle Barough", "seg": "GM",
        "email": "giselle@thrivecausemetics.com", "title": "Growth Marketing Associate, Paid Social", "company": "Thrive Causemetics",
        "domain": "thrivecausemetics.com", "industry": "Beauty / DTC", "size": "201-500",
        "city": "Los Angeles", "region": "California", "country": "US",
        "li": "https://www.linkedin.com/in/giselle-barough-9358541b5/", "li_vanity": "giselle-barough-9358541b5",
        "tw": None, "li_followers": 1027, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "associate", "completeness": 0.83,
        "summary": "Growth marketer focused on paid social across Meta and TikTok; UC Berkeley Haas dual-degree graduate combining data-driven strategy with storytelling.",
        "notes": "Paid-social buyer at a DTC beauty brand — retargeting audiences are her daily unit of work.",
        "intent": 68, "pages": ["/", "/pricing", "/features", "/integrations"],
    },
    {
        "slug": "madelyn_hawkes", "first": "Madelyn", "full": "Madelyn Hawkes", "seg": "GM",
        "email": "madelyn@stitchfix.com", "title": "Sr. Growth Marketing Associate, Paid Social", "company": "Stitch Fix",
        "domain": "stitchfix.com", "industry": "E-commerce / Retail", "size": "5000+",
        "city": "Lehi", "region": "Utah", "country": "US",
        "li": "https://www.linkedin.com/in/madelyn-hawkes/", "li_vanity": "madelyn-hawkes",
        "tw": None, "li_followers": 1013, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "senior", "completeness": 0.86,
        "summary": "Paid social leader with 6 years in performance media; certified in Google Analytics, Google Ads and HubSpot. Has increased user acquisition 35%, cut cost per lead 20% and generated $1M+ in paid-social revenue.",
        "notes": "Senior paid-social owner at a large e-commerce retailer — buys tooling, not just campaigns.",
        "intent": 74, "pages": ["/", "/pricing", "/features", "/case-studies"],
    },
    {
        "slug": "thomas_herron", "first": "Thomas", "full": "Thomas Herron", "seg": "GM",
        "email": "thomas@draftkings.com", "title": "Growth Marketing Senior Associate, Targeted Partnerships", "company": "DraftKings",
        "domain": "draftkings.com", "industry": "Gaming / Sports Betting", "size": "5000+",
        "city": "Boston", "region": "Massachusetts", "country": "US",
        "li": "https://www.linkedin.com/in/thomas-herron-578a1b159/", "li_vanity": "thomas-herron-578a1b159",
        "tw": None, "li_followers": 965, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "senior", "completeness": 0.6,
        "summary": "Senior growth marketing associate on talent and targeted partnerships at DraftKings.",
        "notes": "Partnerships-side growth marketer at a large consumer brand.",
        "intent": 62, "pages": ["/", "/pricing", "/integrations"],
    },
    # --- Founders & marketing leads -----------------------------------------
    {
        "slug": "nivas_ravichandran", "first": "Nivas", "full": "Nivas Ravichandran", "seg": "GM",
        "email": "nivas@spendflo.com", "title": "Head of Marketing", "company": "Spendflo",
        "domain": "spendflo.com", "industry": "SaaS / Procurement", "size": "51-200",
        "city": "San Francisco", "region": "California", "country": "US",
        "li": "https://www.linkedin.com/in/nivas-ravichandran-87926042/", "li_vanity": "nivas-ravichandran-87926042",
        "tw": None, "li_followers": None, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "executive", "completeness": 0.72,
        "summary": "Head of Marketing at Spendflo, a SaaS procurement and spend-management platform.",
        "notes": "Marketing decision-maker with budget authority at a growth-stage B2B SaaS — a real buyer, not an evaluator.",
        "intent": 81, "pages": ["/", "/pricing", "/features", "/case-studies", "/integrations"],
    },
    {
        "slug": "jitendra_jadav", "first": "Jitendra", "full": "Jitendra Jadav", "seg": "GM",
        "email": "j.jadav@lordist.in", "title": "Founder", "company": "Lordist Infotech Private Limited",
        "domain": "lordist.com", "industry": "IT Services", "size": "11-50",
        "city": "Mumbai", "region": "Maharashtra", "country": "IN",
        "li": "https://www.linkedin.com/in/jitendra-jadav-23a568a/", "li_vanity": "jitendra-jadav-23a568a",
        "tw": None, "li_followers": None, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "executive", "completeness": 0.66,
        "summary": "Founder of Lordist Infotech, an IT services company based in Mumbai.",
        "notes": "Agency founder — buys tooling for his own firm and resells to clients.",
        "intent": 59, "pages": ["/", "/pricing", "/integrations"],
    },
    {
        "slug": "bilal_khan", "first": "Bilal", "full": "Bilal (Bill) Khan", "seg": "GM",
        "email": "bilal@platform-people.com.au", "title": "Founder & Recruitment Consultant", "company": "Platform People",
        "domain": "platform-people.com.au", "industry": "Recruitment", "size": "1-10",
        "city": "Sydney", "region": "New South Wales", "country": "AU",
        "li": "https://www.linkedin.com/in/billlkhan/", "li_vanity": "billlkhan",
        "tw": None, "li_followers": None, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "executive", "completeness": 0.68,
        "summary": "Founder and recruitment consultant at Platform People, a Sydney-based recruitment firm.",
        "notes": "Solo founder in recruitment — identifying anonymous site traffic maps directly to candidate and client sourcing.",
        "intent": 64, "pages": ["/", "/pricing", "/features"],
    },
    {
        "slug": "shreeram_rane", "first": "Shreeram", "full": "Shreeram Rane", "seg": "GM",
        "email": "shreeram@ontimeitservices.com", "title": "Founder", "company": "OnTime IT Services India Pvt. Ltd",
        "domain": "ontimeitservices.com", "industry": "IT Services", "size": "51-200",
        "city": "Bengaluru", "region": "Karnataka", "country": "IN",
        "li": "https://www.linkedin.com/in/shreeram-rane-ba65494/", "li_vanity": "shreeram-rane-ba65494",
        "tw": None, "li_followers": None, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "executive", "completeness": 0.55,
        "summary": "Founder of OnTime IT Services India, based in Bengaluru.",
        "notes": "IT services founder. Company domain was not supplied in the source data and is unverified.",
        "intent": 48, "pages": ["/", "/pricing"],
    },
    # --- AI product & engineering leaders (batch 2) -------------------------
    {
        "slug": "owen_price", "first": "Owen", "full": "Owen Price", "seg": "AI",
        "email": "owen@anaconda.com", "title": "Senior Product Manager, AI R&D", "company": "Anaconda, Inc.",
        "domain": "anaconda.com", "industry": "Data Science / AI", "size": "201-500",
        "city": "Denver", "region": "Colorado", "country": "US",
        "li": "https://www.linkedin.com/in/owenhprice/", "li_vanity": "owenhprice",
        "tw": None, "li_followers": 4926, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "manager", "completeness": 0.87,
        "summary": "Hands-on data and analytics leader with 15+ years spanning executive leadership and engineering; former CTO at Kynetec, Microsoft MVP, now in AI R&D product at Anaconda building developer-focused, secure tooling for the AI era.",
        "notes": "Former CTO now shaping AI developer tooling — evaluates API and data quality at depth.",
        "intent": 84, "pages": ["/", "/docs", "/integrations", "/pricing", "/features"],
    },
    {
        "slug": "adrian_gonzalez_sanchez", "first": "Adrián", "full": "Adrián González Sánchez", "seg": "AI",
        "email": "adrian@microsoft.com", "title": "Senior Product Manager, AI & Search", "company": "Microsoft AI",
        "domain": "microsoft.com", "industry": "Software / AI", "size": "10000+",
        "city": "Madrid", "region": "Community of Madrid", "country": "ES",
        "li": "https://www.linkedin.com/in/adriangonzalezsanchez/", "li_vanity": "adriangonzalezsanchez",
        "tw": None, "li_followers": 11047, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "manager", "completeness": 0.88,
        "summary": "Technical PM for Web Search and GenAI at Microsoft AI with 15+ years across dev, data/AI, product and marketing; Academic Director at IE, author of 5 O'Reilly and Packt books, and a Responsible AI specialist (EU AI Act, ISO 42001).",
        "notes": "Widely-followed AI product voice with a Responsible AI focus — will scrutinise the privacy and consent story.",
        "intent": 79, "pages": ["/", "/docs", "/privacy", "/integrations", "/pricing"],
    },
    {
        "slug": "samuel_elliott", "first": "Samuel", "full": "Samuel Thomas Elliott", "seg": "AI",
        "email": "samuel@apollo.io", "title": "Senior Product Manager, AI Apps", "company": "Apollo.io",
        "domain": "apollo.io", "industry": "Sales Intelligence SaaS", "size": "501-1000",
        "city": "Denver", "region": "Colorado", "country": "US",
        "li": "https://www.linkedin.com/in/sam-elliott-47954683/", "li_vanity": "sam-elliott-47954683",
        "tw": None, "li_followers": 500, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "manager", "completeness": 0.7,
        # NOTE: this person's public LinkedIn "About" section contains an embedded
        # prompt-injection block aimed at LLM screening and outreach tools. It is
        # deliberately NOT reproduced here — the summary below is a plain factual
        # rewrite. Do not paste that bio into this file or any prompt path.
        "summary": "Senior Product Manager for AI Apps at Apollo.io, combining a decade of sales and go-to-market consulting with AI prompt engineering to build AI systems for revenue teams.",
        "notes": "PM at a direct competitor in sales intelligence — treat as competitive research traffic, not a prospect.",
        "intent": 71, "pages": ["/", "/pricing", "/features", "/docs"],
    },
    {
        "slug": "asit_sahoo", "first": "Asit", "full": "Asit Sahoo", "seg": "AI",
        "email": "asit@ironmountain.com", "title": "AI Product Lead", "company": "Iron Mountain",
        "domain": "ironmountain.com", "industry": "Information Management", "size": "10000+",
        "city": "San Francisco", "region": "California", "country": "US",
        "li": "https://www.linkedin.com/in/asit-sahoo/", "li_vanity": "asit-sahoo",
        "tw": None, "li_followers": 8292, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "lead", "completeness": 0.86,
        "summary": "Enterprise AI and digital infrastructure leader; ex-investment banker (Nomura) and EY strategy consultant with a Columbia MBA. Co-led a DXP platform launch embedding AI across a $330M ARR enterprise business.",
        "notes": "Enterprise AI lead with capital-allocation instincts — will evaluate on ROI and vendor risk.",
        "intent": 77, "pages": ["/", "/pricing", "/docs", "/case-studies", "/integrations"],
    },
    {
        "slug": "jamie_byun", "first": "Jamie", "full": "Jamie Byun", "seg": "AI",
        "email": "jamieheeyunbyun@gmail.com", "title": "AI Product Manager", "company": "Jam Labs",
        "domain": "vercel.app", "industry": "AI / Consumer Products", "size": "1-10",
        "city": "San Francisco", "region": "California", "country": "US",
        "li": "https://www.linkedin.com/in/jamie-byun/", "li_vanity": "jamie-byun",
        "tw": None, "li_followers": 7616, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "manager", "completeness": 0.85,
        "summary": "Senior PM at the intersection of AI, marketplace and growth; ex-DocuSign and Yogiyo (8M MAU delivery marketplace), now building Guest AI, a multilingual LLM-powered chatbot for SMBs.",
        "notes": "Solo AI builder shipping an LLM product — the technical evaluator persona.",
        "intent": 75, "pages": ["/", "/docs", "/integrations", "/pricing"],
    },
    {
        "slug": "cindy_cao", "first": "Cindy", "full": "Cindy Cao, MBA", "seg": "AI",
        "email": "cindy@hcsc.com", "title": "Principal AI Product Manager", "company": "Health Care Service Corporation",
        "domain": "hcsc.com", "industry": "Health Insurance", "size": "10000+",
        "city": "Chicago", "region": "Illinois", "country": "US",
        "li": "https://www.linkedin.com/in/cindy-xu-cao/", "li_vanity": "cindy-xu-cao",
        "tw": None, "li_followers": None, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "principal", "completeness": 0.58,
        "summary": "Principal AI Product Manager at Health Care Service Corporation.",
        "notes": "Principal AI PM in a heavily regulated industry — privacy and compliance are gating criteria.",
        "intent": 66, "pages": ["/", "/privacy", "/docs", "/pricing"],
    },
    {
        "slug": "zaid_khatib", "first": "Zaid", "full": "Zaid Khatib", "seg": "AI",
        "email": "zaid@duolingo.com", "title": "Senior Product Manager, AI Research & Assessment", "company": "Duolingo",
        "domain": "duolingo.com", "industry": "EdTech", "size": "501-1000",
        "city": "New York", "region": "New York", "country": "US",
        "li": "https://www.linkedin.com/in/zaid-khatib/", "li_vanity": "zaid-khatib",
        "tw": None, "li_followers": None, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "manager", "completeness": 0.58,
        "summary": "Senior Product Manager for AI Research and Assessment Development at Duolingo.",
        "notes": "AI research PM at a consumer EdTech leader.",
        "intent": 68, "pages": ["/", "/docs", "/features"],
    },
    {
        "slug": "emily_worsley", "first": "Emily", "full": "Emily Worsley", "seg": "AI",
        "email": "emily@pointclickcare.com", "title": "AI Product Manager", "company": "PointClickCare",
        "domain": "pointclickcare.com", "industry": "Healthcare SaaS", "size": "1000-5000",
        "city": "Brooklyn", "region": "New York", "country": "US",
        "li": "https://www.linkedin.com/in/emily-worsley-545103162/", "li_vanity": "emily-worsley-545103162",
        "tw": None, "li_followers": None, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "manager", "completeness": 0.58,
        "summary": "AI Product Manager at PointClickCare, a healthcare SaaS platform.",
        "notes": "AI PM in healthcare SaaS — evaluating identity and enrichment sources under HIPAA constraints.",
        "intent": 64, "pages": ["/", "/privacy", "/docs", "/pricing"],
    },
    {
        "slug": "kevyn_eva_norton", "first": "Kevyn", "full": "Kevyn Eva Norton", "seg": "AI",
        "email": "kevyn@easybitesapp.com", "title": "Product Lead, AI-powered Child Feeding App", "company": "Easy Bites App",
        "domain": "easybitesapp.com", "industry": "Consumer Health App", "size": "1-10",
        "city": "Zurich", "region": "Zurich", "country": "CH",
        "li": "https://www.linkedin.com/in/kevyneva/", "li_vanity": "kevyneva",
        "tw": None, "li_followers": None, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "lead", "completeness": 0.57,
        "summary": "Product Lead for Easy Bites, an AI-powered child feeding app based in Zurich.",
        "notes": "Early-stage AI product lead in EU — GDPR posture will decide the evaluation.",
        "intent": 55, "pages": ["/", "/privacy", "/pricing"],
    },
    {
        "slug": "vivek_s", "first": "Vivek", "full": "Vivek S.", "seg": "AI",
        "email": "vivek@workato.com", "title": "Senior Product Manager, AI Apps", "company": "Workato",
        "domain": "workato.com", "industry": "iPaaS / Automation", "size": "1000-5000",
        "city": "San Francisco", "region": "California", "country": "US",
        "li": "https://www.linkedin.com/in/vivek-ks-88910910/", "li_vanity": "vivek-ks-88910910",
        "tw": None, "li_followers": None, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "manager", "completeness": 0.58,
        "summary": "Senior Product Manager for AI Apps at Workato, an enterprise automation and integration platform.",
        "notes": "PM at an iPaaS vendor — most likely evaluating Beam as an integration target, not just a tool.",
        "intent": 72, "pages": ["/", "/docs", "/integrations", "/pricing"],
    },
    {
        "slug": "jason_zheng", "first": "Jason", "full": "Jason Zheng", "seg": "AI",
        "email": "jason@syndio.com", "title": "Product Manager, AI / Decision Intelligence", "company": "Syndio",
        "domain": "syndio.com", "industry": "HR Tech", "size": "201-500",
        "city": "Seattle", "region": "Washington", "country": "US",
        "li": "https://www.linkedin.com/in/jasonzheng1/", "li_vanity": "jasonzheng1",
        "tw": None, "li_followers": None, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "manager", "completeness": 0.58,
        "summary": "Product Manager for AI and decision intelligence at Syndio, a workplace equity analytics platform.",
        "notes": "Decision-intelligence PM — cares about data provenance and confidence scoring.",
        "intent": 63, "pages": ["/", "/docs", "/features"],
    },
    {
        "slug": "serena_tan", "first": "Serena", "full": "Serena (Jiaqi) Tan", "seg": "AI",
        "email": "serena@gehealthcare.com", "title": "Sr Product Manager, AI", "company": "GE HealthCare",
        "domain": "gehealthcare.com", "industry": "MedTech / AI", "size": "10000+",
        "city": "San Francisco", "region": "California", "country": "US",
        "li": "https://www.linkedin.com/in/serena-jiaqi-tan/", "li_vanity": "serena-jiaqi-tan",
        "tw": None, "li_followers": None, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "senior", "completeness": 0.58,
        "summary": "Senior Product Manager for AI at GE HealthCare.",
        "notes": "Senior AI PM at a large MedTech — long procurement cycle, high contract value.",
        "intent": 67, "pages": ["/", "/pricing", "/docs", "/privacy"],
    },
    {
        "slug": "kranthi_bathula", "first": "Kranthi", "full": "Kranthi Bathula", "seg": "AI",
        "email": "kranthi@proctor360.com", "title": "AI Product Manager", "company": "Proctor360",
        "domain": "proctor360.com", "industry": "EdTech / Proctoring", "size": "11-50",
        "city": "Richmond", "region": "Virginia", "country": "US",
        "li": "https://www.linkedin.com/in/kranthibathula/", "li_vanity": "kranthibathula",
        "tw": None, "li_followers": None, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "manager", "completeness": 0.57,
        "summary": "AI Product Manager at Proctor360, an online exam proctoring platform.",
        "notes": "AI PM at a small EdTech — fast decision cycle, price-sensitive.",
        "intent": 60, "pages": ["/", "/pricing", "/docs"],
    },
    {
        "slug": "soumyo_mitra", "first": "Soumyo", "full": "Soumyo Mitra", "seg": "AI",
        "email": "soumyo@c3.ai", "title": "Product Lead, AI Applications", "company": "C3 AI",
        "domain": "c3.ai", "industry": "Enterprise AI", "size": "501-1000",
        "city": None, "region": None, "country": "US",
        "li": "https://www.linkedin.com/in/soumyomitra/", "li_vanity": "soumyomitra",
        "tw": None, "li_followers": None, "tw_followers": None, "tw_bio": None, "tw_topics": [],
        "seniority": "lead", "completeness": 0.56,
        "summary": "Product Lead for AI Applications at C3 AI, an enterprise AI application platform.",
        "notes": "Product lead at an enterprise AI vendor — evaluating identity data as an input to AI applications.",
        "intent": 70, "pages": ["/", "/docs", "/integrations", "/pricing"],
    },
]
# fmt: on

# Real published blog slugs on getbeam.fyi/blog — seeded visitors "enter" via one
# (matched to persona) so their journey reads: read blog -> landing -> product.
BLOG_GM = [
    "follow-up-with-website-visitors-5-sequences-that-convert",
    "how-to-follow-up-with-warm-website-visitors-and-convert",
    "how-to-follow-up-with-warm-leads-and-close-more-deals",
]
BLOG_AI = [
    "get-started-with-visitor-identification-b2b-setup-guide",
    "website-visitor-identification-turn-anonymous-traffic-into-leads",
]
# Only these ~3 visitors entered via a blog post; everyone else came direct /
# via Google to a product page. (Not everyone reads the blog first — realistic.)
BLOG_READERS = {"erika_marietta", "mae_jauch", "radhika_khandelwal"}

# Real LinkedIn posts, pasted by the owner (LinkedIn has NO public crawl API, so
# these are entered by hand — verbatim from the person's public LinkedIn).
#   slug -> [{"text": "...", "url": "https://www.linkedin.com/posts/...", "days_ago": 3}]
# "url" and "days_ago" optional. Fill, then re-seed. Slugs left out just show no
# LinkedIn-posts block for that visitor (matched to the person's LinkedIn vanity).
LINKEDIN_POSTS: dict[str, list[dict]] = {
    "radhika_khandelwal": [
        {
            "text": (
                "Your API spec is probably useless to an AI agent. Here's why and how to fix it.\n\n"
                "We have massive context windows now. Just dump the spec in, right? Wrong.\n\n"
                "Kin Lane is one of those people who has shaped how the entire industry thinks "
                "about APIs — and when someone like that says we're doing something wrong, you "
                "put your phone down and listen. His thesis: Enrich the Spec. Ship the Sandbox. "
                "Let the Agents Learn.\n\n"
                "Handing an AI agent a full API spec is like dropping a new hire into a 10,000 "
                "page company wiki and saying \"figure it out.\" Technically everything they need "
                "is in there. But they'll drown before they find anything useful.\n\n"
                "So instead of dumping everything in, you shape the spec before the agent ever sees it:\n"
                "→ Tags carve your API into meaningful domains — customers, billing, support.\n"
                "→ Named Examples show the agent what real data looks like.\n"
                "→ Overlays let you filter the spec down to only what's relevant.\n"
                "→ That scoped, enriched spec becomes the sandbox.\n\n"
                "Bigger context window ≠ smarter agent. More noise means more hallucinations and "
                "an agent that confidently does the wrong thing.\n\n"
                "Less API. More signal. Better agent."
            ),
            "url": "https://www.linkedin.com/posts/radhikaakhandelwal_github-naftikosandboxes-this-are-all-share-7461427159514062848-iWzS/",
            "days_ago": 3,
        },
        {
            "text": (
                "We're proud to announce a multi-year, major strategic partnership with Nityo "
                "Infotech, a global IT leader operating in 40+ countries with 31,000+ employees. "
                "Together, we're bringing the agentic workforce to enterprises around the world "
                "at unprecedented scale.\n\n"
                "Enterprises have reached the limits of pilots and prototypes. What they need "
                "next is a governed, production-ready workforce where AI agents execute real work "
                "alongside human teams. This partnership is built precisely for that shift.\n\n"
                "By combining Nityo's global delivery capabilities with Wand AI's patented "
                "operating system for the agentic workforce, organizations can now redesign core "
                "functions — finance, risk, operations, legal, HR, procurement — into hybrid "
                "human + agent workforces.\n\n"
                "This collaboration is not about tools. It is about workforce transformation. "
                "I'm incredibly proud of what our team at Wand has built to make this possible."
            ),
            "url": "https://www.linkedin.com/posts/radhikaakhandelwal_were-proud-to-announce-a-multi-year-major-share-7400296496568639490-uB9F/",
            "days_ago": 30,
        },
        {
            "text": (
                "We're growing at Wand AI — and if building at the cutting edge of AI excites "
                "you, and you thrive where the problems are hard and the impact is real, this "
                "might just be your sign 👀\n\n"
                "We're hiring for:\n"
                "🇺🇸 Sales Engineer – USA (Remote/Hybrid)\n"
                "🇦🇪 Sales Engineer – Abu Dhabi (On-site/Hybrid)\n"
                "👩‍💻 Engineering Manager\n\n"
                "We're building something special here — and if you (or someone you know) is the "
                "kind of person who wants to shape how AI gets built and used in the real world… "
                "come join us.\n\n#WandAI #SalesEngineer #EngineeringManager #AI"
            ),
            "url": "https://www.linkedin.com/posts/radhikaakhandelwal_wandai-salesengineer-engineeringmanager-share-7387929029011587072-SC6V/",
            "days_ago": 45,
        },
    ],
}

SEG_ANGLE = {
    "AI": "Speak to API depth, data quality and how identity resolution plugs into an AI or agent workflow — technical and concrete, not generic benefits.",
    "GM": "Speak to pipeline and retargeting ROI: turning anonymous traffic into named leads is the core growth job. Direct and numbers-first.",
}

SEGMENTS = {
    "AI": {
        "name": "AI Product & Engineering Leaders",
        "description": "Product and engineering leaders building AI/agent products — evaluating Beam for identity data and API fit.",
        "priority": "medium",
        "channels": ["email", "linkedin"],
        "titles": ["AI Product Manager", "AI Product Lead", "Director of AI Product"],
        "industries": ["AI & Machine Learning", "Software", "Semiconductors / AI"],
    },
    "GM": {
        "name": "Growth Marketing Team",
        "description": "Hands-on growth and digital marketers — the day-to-day users who turn site traffic into pipeline.",
        "priority": "high",
        "channels": ["email", "linkedin"],
        "titles": ["Growth Marketing Associate", "Digital Marketing Coordinator", "CMO"],
        "industries": ["Growth Marketing", "SaaS", "FinTech", "Retail"],
    },
}


def _location(lead: dict) -> str:
    parts = [lead.get("city"), lead.get("region"), lead.get("country")]
    return ", ".join(p for p in parts if p) or "United States"


def _deep_research(lead: dict) -> str:
    return (
        f"## Professional snapshot\n"
        f"{lead['full']} is {lead['title']} at {lead['company']} "
        f"({lead['industry']}), based in {_location(lead)}. {lead['notes']}\n\n"
        f"## Why they're a fit\n"
        f"Visited high-intent pages ({', '.join(lead['pages'])}) across multiple sessions — "
        f"an active-evaluation signal, and squarely in Beam's ideal-customer profile.\n\n"
        f"## Recommended angle\n{SEG_ANGLE[lead['seg']]}"
    )


def _social_context(lead: dict) -> dict:
    resolved = (NOW - timedelta(hours=6)).replace(tzinfo=timezone.utc).isoformat()
    profiles = [
        {
            "site_name": "LinkedIn", "category": "professional", "url": lead["li"],
            "kind": "profile", "confidence": "confirmed", "source_engine": "pdl",
            "extra": {"username": lead["li_vanity"], "followers": lead.get("li_followers")},
        }
    ]
    if lead.get("tw"):
        profiles.append({
            "site_name": "X", "category": "social", "url": f"https://x.com/{lead['tw']}",
            "kind": "profile", "confidence": "confirmed", "source_engine": "pdl",
            "extra": {"username": lead["tw"], "followers": lead.get("tw_followers")},
        })
    profiles.append({
        "site_name": "Company site", "category": "work", "url": f"https://{lead['domain']}",
        "kind": "profile", "confidence": "likely", "source_engine": "rule_base",
        "extra": {"name": lead["company"]},
    })
    confirmed = sum(1 for p in profiles if p["confidence"] == "confirmed")
    likely = sum(1 for p in profiles if p["confidence"] == "likely")
    candidates = [lead["li_vanity"]] + ([lead["tw"]] if lead.get("tw") else [])
    return {
        "social_resolution": {
            "status": "complete",
            "resolved_at": resolved,
            "stages_run": ["enrich", "osint_free", "rule_base"],
            "profiles": profiles,
            "guesses": [],
            "paid": {"used": False, "provider": "osint-industries", "found": 0, "cached": False, "error": None},
            "summary": {
                "profile_count": len(profiles), "confirmed_count": confirmed,
                "likely_count": likely, "guess_count": 0, "candidates_used": candidates,
            },
            "message": f"{confirmed} verified profile(s), {likely} likely",
        },
        "deep_research": _deep_research(lead),
        "researched_at": resolved,
        "model": "gemini-2.5-flash",
        "_demo_seed": True,
    }


def _try_email_bidx(email: str) -> str | None:
    """Compute the blind index if a PII key is configured; skip gracefully if not."""
    try:
        from apps.api.services.pii_crypto import email_hash
        return email_hash(email)
    except Exception:
        return None


async def resolve_site(db, override: str | None) -> Site:
    if override:
        site = (await db.execute(select(Site).where(Site.site_id == override))).scalar_one_or_none()
        if not site:
            print(f"No site with site_id={override!r}.")
            await _print_sites(db)
            raise SystemExit(1)
        return site
    rows = (await db.execute(select(Site).where(Site.url.ilike("%getbeam.fyi%")))).scalars().all()
    if not rows:
        print("No site found whose URL contains 'getbeam.fyi'.")
        await _print_sites(db)
        raise SystemExit(1)
    if len(rows) > 1:
        print(f"WARNING: {len(rows)} sites match getbeam.fyi — using the first. "
              f"Pass --site-id to be explicit.")
    return rows[0]


async def _print_sites(db) -> None:
    sites = (await db.execute(select(Site))).scalars().all()
    if not sites:
        print("  (no sites exist in this database)")
        return
    print("Available sites:")
    for s in sites:
        print(f"  site_id={s.site_id!r}  url={s.url!r}  name={s.name!r}")


async def _wipe_segments_campaigns(db, site_id: str) -> dict:
    """Delete demo-era segments + campaigns for this site.

    Catches BOTH the tagged pre-built rows (characteristics/plan._demo_seed) AND
    rows the live AI buttons created during rehearsal/demo takes (untagged —
    identified by having a seeded demo visitor among their members/recipients).
    """
    counts = {}
    vids = set(_demo_vid(l["slug"]) for l in LEADS)

    segs = (await db.execute(select(Segment).where(Segment.site_id == site_id))).scalars().all()
    demo_seg_ids = set()
    for s in segs:
        if isinstance(s.characteristics, dict) and s.characteristics.get("_demo_seed"):
            demo_seg_ids.add(s.id)
            continue
        member_ids = {
            m.visitor_id for m in (await db.execute(
                select(SegmentMember).where(SegmentMember.segment_id == s.id)
            )).scalars().all()
        }
        if member_ids & vids:
            demo_seg_ids.add(s.id)

    camps = (await db.execute(select(Campaign).where(Campaign.site_id == site_id))).scalars().all()
    demo_camps = [
        c for c in camps
        if (isinstance(c.plan, dict) and c.plan.get("_demo_seed")) or c.segment_id in demo_seg_ids
    ]
    for c in demo_camps:
        for tp in (await db.execute(
            select(CampaignTouchpoint).where(CampaignTouchpoint.campaign_id == c.id)
        )).scalars().all():
            await db.delete(tp)
        await db.delete(c)
    counts["campaigns"] = len(demo_camps)

    for s in [s for s in segs if s.id in demo_seg_ids]:
        for m in (await db.execute(
            select(SegmentMember).where(SegmentMember.segment_id == s.id)
        )).scalars().all():
            await db.delete(m)
        await db.delete(s)
    counts["segments"] = len(demo_seg_ids)
    return counts


async def wipe(db, site_id: str) -> dict:
    """Remove all demo rows for this site. Order respects FKs."""
    counts = await _wipe_segments_campaigns(db, site_id)

    # Visitor-scoped rows. Match on: current slug ids + any enrichment row tagged
    # social_context._demo_seed (catches visitors from a PRIOR roster whose slugs
    # changed) + legacy-prefixed leftovers.
    vids = set(_demo_vid(l["slug"]) for l in LEADS)
    enr_all = (await db.execute(
        select(EnrichmentProfile).where(EnrichmentProfile.site_id == site_id)
    )).scalars().all()
    vids |= {
        e.visitor_id for e in enr_all
        if isinstance(e.social_context, dict) and e.social_context.get("_demo_seed")
    }
    demo_match = lambda m: or_(m.visitor_id.in_(vids), m.visitor_id.like(f"{_LEGACY_PREFIX}%"))
    for model in (EnrichmentProfile, IdentifiedVisitor, Visitor):
        rows = (await db.execute(
            select(model).where(model.site_id == site_id, demo_match(model))
        )).scalars().all()
        for r in rows:
            await db.delete(r)
        counts[model.__tablename__] = len(rows)

    ev = (await db.execute(
        select(Event).where(Event.site_id == site_id, demo_match(Event))
    )).scalars().all()
    for e in ev:
        await db.delete(e)
    counts["events"] = len(ev)

    # Seeded social posts (by marker) + the synthetic feed account (cascades any
    # remaining posts). Marker-scoped so real connected accounts are untouched.
    posts = (await db.execute(
        select(Post).where(Post.platform_post_id.like(f"{_POST_MARKER}%"))
    )).scalars().all()
    for p in posts:
        await db.delete(p)
    counts["posts"] = len(posts)
    accts = (await db.execute(
        select(SocialAccount).where(SocialAccount.platform_user_id == _FEED_ACCT_MARKER)
    )).scalars().all()
    for a in accts:
        await db.delete(a)
    counts["social_accounts"] = len(accts)

    await db.commit()
    return counts


async def stage_live(db, site: Site) -> None:
    """Prep a LIVE-button demo: wipe the pre-built segment/campaign displays and
    hide the social feed, but keep the 11 identified+enriched visitors.

    On camera the owner then presses the real buttons:
      - Segments  -> "Re-run segmentation"  (real Gemini run over all enriched)
      - Segment card -> "Generate campaign" (real Gemini campaign plan)

    Auto-segmentation stays dormant BY DESIGN: the auto trigger only counts
    enriched visitors with segmented=False (needs 10+), and we keep the seeded
    11 at segmented=True. The manual /run endpoint doesn't filter on segmented,
    so the button still picks all of them. No env/product change needed.

    Safety: live-created campaigns have no pre-sent touchpoints, so this sets
    do_not_email=True on all seeded identities — if "Send emails" is ever
    pressed, every recipient is skipped (0 real emails).
    """
    site_id = site.site_id

    # 1) Remove segment + campaign displays (pre-built AND button-created).
    counts = await _wipe_segments_campaigns(db, site_id)
    print(f"  cleared displays: {counts}")

    # 2) Keep seeded visitors segmented=True (auto trigger dormant) + block sends.
    from sqlalchemy import update
    vids = [_demo_vid(l["slug"]) for l in LEADS]
    await db.execute(
        update(Visitor).where(Visitor.site_id == site_id, Visitor.visitor_id.in_(vids))
        .values(segmented=True)
    )
    # Everyone EXCEPT the owner: the owner's row keeps do_not_email=False so an
    # on-camera "Send emails" delivers exactly one real email — to his own inbox.
    owner_vid = _demo_vid("thai_tran")
    await db.execute(
        update(IdentifiedVisitor)
        .where(
            IdentifiedVisitor.site_id == site_id,
            IdentifiedVisitor.visitor_id.in_([v for v in vids if v != owner_vid]),
        )
        .values(do_not_email=True)
    )
    await db.execute(
        update(IdentifiedVisitor)
        .where(IdentifiedVisitor.site_id == site_id, IdentifiedVisitor.visitor_id == owner_vid)
        .values(do_not_email=False)
    )

    # 3) Hide the social feed (posts + sync both keyed on is_active).
    await _set_posts_active(db, site, False)
    await db.commit()


async def _set_posts_active(db, site: Site, active: bool) -> None:
    acct = (await db.execute(
        select(SocialAccount).where(
            SocialAccount.user_id == site.user_id,
            SocialAccount.platform_user_id == _FEED_ACCT_MARKER,
        )
    )).scalar_one_or_none()
    if acct is not None:
        acct.is_active = active


async def seed(db, site: Site) -> None:
    site_id = site.site_id
    await wipe(db, site_id)  # idempotent: clean slate

    # 1) Visitors + identity + enrichment + events
    for lead in LEADS:
        vid = _demo_vid(lead["slug"])
        # Deterministic per-person variation (stable across re-runs) so pageview
        # and session counts look organic, not uniform.
        rng = random.Random(lead["slug"])
        # Only a few visitors entered via a real blog post (then landing + product);
        # the rest came direct / via Google straight to a product page.
        if lead["slug"] in BLOG_READERS:
            blogs = BLOG_GM if lead["seg"] == "GM" else BLOG_AI
            blog_paths = [f"/blog/{s}" for s in rng.sample(blogs, 1)]
            pages = list(dict.fromkeys(blog_paths + lead["pages"]))[:6]
        else:
            pages = lead["pages"]
        sessions = rng.randint(2, 3 + lead["intent"] // 22)  # ~2-6
        if lead["intent"] < 68 and rng.random() < 0.35:
            sessions = 1
        n_pv = max(sum(rng.randint(1, 5) for _ in range(sessions)), len(lead["pages"]))
        first_seen = NOW - timedelta(days=rng.randint(6, 22), hours=rng.randint(0, 23))
        last_seen = NOW - timedelta(hours=rng.randint(1, 96), minutes=rng.randint(0, 59))
        if last_seen <= first_seen:
            last_seen = first_seen + timedelta(hours=2)
        span = (last_seen - first_seen).total_seconds()
        db.add(Visitor(
            site_id=site_id, visitor_id=vid,
            first_seen=first_seen, last_seen=last_seen,
            total_pageviews=n_pv, total_sessions=sessions,
            avg_time_on_page=float(rng.randint(25, 165)),
            max_scroll_depth=rng.randint(45, 100),
            pages_visited=pages,
            top_referrer="https://www.google.com/", utm_source="google", utm_medium="organic",
            country_code=lead["country"], device_type="desktop",
            company_domain=lead["domain"],
            intent_score=float(lead["intent"]),
            identity_status="identified", enrichment_status="enriched",
            segmented=True,
        ))
        db.add(IdentifiedVisitor(
            site_id=site_id, visitor_id=vid,
            email=lead["email"], full_name=lead["full"],
            city=lead["city"], region=lead["region"], country=lead["country"],
            resolution_provider="form_capture", confidence_score=0.95,
            do_not_email=False, email_bidx=_try_email_bidx(lead["email"]),
        ))
        db.add(EnrichmentProfile(
            site_id=site_id, visitor_id=vid,
            job_title=lead["title"], company_name=lead["company"],
            company_size=lead["size"], industry=lead["industry"],
            seniority_level=lead.get("seniority", "manager"),
            linkedin_url=lead["li"], twitter_handle=lead.get("tw"),
            personal_website=f"https://{lead['domain']}",
            linkedin_headline=f"{lead['title']} at {lead['company']}",
            linkedin_summary=lead.get("summary"), linkedin_follower_count=lead.get("li_followers"),
            twitter_bio=lead.get("tw_bio"), twitter_follower_count=lead.get("tw_followers"),
            twitter_recent_topics=lead.get("tw_topics", []),
            social_context=_social_context(lead),
            social_context_updated_at=(NOW - timedelta(hours=6)).replace(tzinfo=timezone.utc),
            enrichment_completeness=lead.get("completeness", 0.85),
        ))
        for k in range(n_pv):
            frac = k / max(n_pv - 1, 1)
            ts = first_seen + timedelta(seconds=span * frac)
            db.add(Event(
                site_id=site_id, visitor_id=vid, event_type="pageview",
                url=f"https://getbeam.fyi{pages[k % len(pages)]}",
                page_path=pages[k % len(pages)],
                referrer="https://www.google.com/", utm_source="google", utm_medium="organic",
                country_code=lead["country"], region=lead["region"] or "",
                device_type="desktop", scroll_depth=rng.randint(40, 100),
                time_on_page=rng.randint(15, 180),
                created_at=ts,
            ))
    await db.flush()

    # 2) Segments + members
    seg_ids: dict[str, object] = {}
    for key, cfg in SEGMENTS.items():
        members = [l for l in LEADS if l["seg"] == key]
        avg = round(sum(l["intent"] for l in members) / len(members), 1)
        seg = Segment(
            site_id=site_id, name=cfg["name"], description=cfg["description"],
            priority=cfg["priority"], recommended_channels=cfg["channels"],
            messaging_angle=SEG_ANGLE[key], visitor_count=len(members),
            characteristics={
                "common_job_titles": cfg["titles"],
                "common_industries": cfg["industries"],
                "common_behaviors": ["Viewed pricing", "Multiple sessions", "Ideal-customer fit"],
                "avg_intent_score": avg,
                "_demo_seed": True,
            },
        )
        db.add(seg)
        await db.flush()
        seg_ids[key] = seg.id
        for l in members:
            db.add(SegmentMember(segment_id=seg.id, visitor_id=_demo_vid(l["slug"]), site_id=site_id))
    await db.flush()

    # 3) Campaigns + pre-sent touchpoints (block real sends during demo)
    campaigns = [
        {
            "seg": "GM", "status": "active", "type": "email", "platform": None,
            "name": "Turn Anonymous Traffic Into Named Leads",
            "approved_at": NOW - timedelta(days=3), "started_at": NOW - timedelta(days=2),
            "plan": {
                "campaign_name": "Turn Anonymous Traffic Into Named Leads",
                "total_touchpoints": 2, "success_metric": "Booked demos",
                "estimated_reach": "6 growth marketers",
                "touchpoints": [
                    {"order": 1, "step": 1, "channel": "email", "delay_hours_from_start": 0,
                     "subject": "{{first_name}}, saw you on our pricing page",
                     "body": "Hi {{first_name}},\n\nNoticed you spent some time on our pricing page this week. Beam turns the anonymous visitors already hitting your site into named, ready-to-reach leads — no extra ad spend.\n\nWorth a quick 15 minutes to see the leads we'd surface for you?\n\n— The Beam team",
                     "cta": "Book a 15-min demo",
                     "personalization_fields": ["first_name"]},
                    {"order": 2, "channel": "linkedin", "delay_hours_from_start": 48,
                     "connection_note": "Hi {{first_name}} — fellow growth marketer here. Mind if I connect?",
                     "followup_message": "Thanks for connecting! Quick one — would seeing which companies visit your site (by name) help your pipeline?",
                     "personalization_fields": ["first_name"]},
                ],
                "_demo_seed": True,
            },
        },
        {
            "seg": "AI", "status": "draft", "type": "email", "platform": None,
            "name": "AI Product Leaders — Identity API Intro",
            "approved_at": None, "started_at": None,
            "plan": {
                "campaign_name": "AI Product Leaders — Identity API Intro",
                "total_touchpoints": 2, "success_metric": "Sandbox API sign-ups",
                "estimated_reach": "5 AI product leaders",
                "touchpoints": [
                    {"order": 1, "step": 1, "channel": "email", "delay_hours_from_start": 0,
                     "subject": "{{first_name}} — identity resolution API for your stack",
                     "body": "Hi {{first_name}},\n\nSaw your team exploring Beam. On the technical side: deterministic device-graph matching, webhook events, and a clean API to push identified visitors straight into your product or data stack.\n\nHappy to share the docs and a sandbox key.\n\n— The Beam team",
                     "cta": "Get a sandbox API key",
                     "personalization_fields": ["first_name"]},
                    {"order": 2, "channel": "linkedin", "delay_hours_from_start": 48,
                     "connection_note": "Hi {{first_name}} — building in the AI/identity space, would love to connect.",
                     "followup_message": "Thanks for connecting! Curious whether identity resolution is on your roadmap right now.",
                     "personalization_fields": ["first_name"]},
                ],
                "_demo_seed": True,
            },
        },
        {
            "seg": "GM", "status": "approved", "type": "email", "platform": None,
            "name": "Growth Team — Pricing Page Re-Engagement",
            "approved_at": NOW - timedelta(days=1), "started_at": None,
            "plan": {
                "campaign_name": "Growth Team — Pricing Page Re-Engagement",
                "total_touchpoints": 2, "success_metric": "Reply / sample requested",
                "estimated_reach": "6 growth marketers",
                "touchpoints": [
                    {"order": 1, "step": 1, "channel": "email", "delay_hours_from_start": 0,
                     "subject": "{{first_name}}, the leads you left on the table",
                     "body": "Hi {{first_name}},\n\nA chunk of your site traffic bounces without ever converting. Beam identifies those visitors so your team can follow up while intent is still high.\n\nCan I send over a sample of who visited this week?\n\n— The Beam team",
                     "cta": "See a sample lead list",
                     "personalization_fields": ["first_name"]},
                    {"order": 2, "channel": "linkedin", "delay_hours_from_start": 24,
                     "connection_note": "Hi {{first_name}} — quick question about your growth stack, mind connecting?",
                     "followup_message": "Thanks! Would a weekly list of named site visitors be useful to your team?",
                     "personalization_fields": ["first_name"]},
                ],
                "_demo_seed": True,
            },
        },
    ]

    for c in campaigns:
        members = [l for l in LEADS if l["seg"] == c["seg"]]
        camp = Campaign(
            site_id=site_id, segment_id=seg_ids[c["seg"]], name=c["name"],
            campaign_type=c["type"], platform=c["platform"], status=c["status"],
            plan=c["plan"], approved_at=c["approved_at"], started_at=c["started_at"],
        )
        db.add(camp)
        await db.flush()
        # Pre-sent email touchpoints => send_campaign_emails() skips everyone (no real emails).
        for i, l in enumerate(members):
            opened = (NOW - timedelta(days=1, hours=i)) if i % 5 < 3 else None
            clicked = (NOW - timedelta(hours=6 + i)) if i % 5 < 2 else None
            db.add(CampaignTouchpoint(
                campaign_id=camp.id, visitor_id=_demo_vid(l["slug"]),
                channel="email", touchpoint_order=1, status="sent",
                content={"subject": c["plan"]["touchpoints"][0]["subject"]},
                sent_at=NOW - timedelta(days=1, hours=i + 2),
                opened_at=opened, clicked_at=clicked,
            ))

    # 4) Social "visitor feed": pull REAL public tweets for the seeded handles.
    # A synthetic owner-owned account carries them; sync_visitor_posts reads every
    # enrichment twitter_handle for this owner and fetches via the syndication
    # scraper. No fake tweets — a handle with no public activity just yields none.
    acct = (await db.execute(
        select(SocialAccount).where(
            SocialAccount.user_id == site.user_id,
            SocialAccount.platform_user_id == _FEED_ACCT_MARKER,
        )
    )).scalar_one_or_none()
    if acct is None:
        acct = SocialAccount(
            user_id=site.user_id, platform=Platform.twitter,
            platform_user_id=_FEED_ACCT_MARKER, username="getbeam",
            access_token="seeded-demo-token", is_active=True,
        )
        db.add(acct)
        await db.flush()
    await db.commit()

    from apps.api.services.sync import sync_visitor_posts
    try:
        real_n = await sync_visitor_posts(db, acct)
    except Exception as exc:  # network/scraper hiccup — don't fail the whole seed
        real_n = 0
        print(f"  (real-post sync error: {exc})")
    handled = [l["tw"] for l in LEADS if l.get("tw")]
    print(f"  real tweets fetched: {real_n} (from handles: {', '.join('@' + h for h in handled) or 'none'})")

    # Real LinkedIn posts pasted by the owner (LinkedIn can't be crawled) → stored
    # as platform=linkedin visitor-feed posts, matched to the visitor's LinkedIn
    # vanity by the detail page's "Recent LinkedIn posts" block.
    lead_by_slug = {l["slug"]: l for l in LEADS}
    li_n = 0
    for slug, items in LINKEDIN_POSTS.items():
        lead = lead_by_slug.get(slug)
        if not lead:
            print(f"  (skip LinkedIn posts for unknown slug {slug!r})")
            continue
        for j, it in enumerate(items):
            li_n += 1
            db.add(Post(
                social_account_id=acct.id, platform=Platform.linkedin,
                platform_post_id=f"{_POST_MARKER}li_{slug}_{j}",
                author_name=lead["full"], author_username=lead["li_vanity"],
                content=it["text"], source="visitors",
                post_url=it.get("url") or lead["li"],
                posted_at=(NOW - timedelta(days=it.get("days_ago", j + 1))).replace(tzinfo=timezone.utc),
            ))
    if li_n:
        await db.commit()
    print(f"  linkedin posts seeded: {li_n}")


async def main() -> None:
    ap = argparse.ArgumentParser(description="Seed/remove getbeam.fyi demo visitors.")
    ap.add_argument("--site-id", default=None, help="Target site_id (default: auto-detect getbeam.fyi)")
    ap.add_argument("--dry-run", action="store_true", help="Detect site + print plan, no writes")
    ap.add_argument("--unseed", action="store_true", help="Remove all demo rows and exit")
    ap.add_argument("--stage-live", action="store_true",
                    help="Live-demo prep: wipe segment/campaign displays + hide posts; keep visitors")
    ap.add_argument("--posts", choices=["on", "off"], default=None,
                    help="Show/hide the seeded social posts (flips the demo feed account)")
    args = ap.parse_args()

    host = engine.url.host or "?"
    print(f"DB host: {host}")

    async with async_session() as db:
        site = await resolve_site(db, args.site_id)
        owner = (await db.execute(select(User).where(User.id == site.user_id))).scalar_one_or_none()
        print(f"Target site: site_id={site.site_id!r}  url={site.url!r}  name={site.name!r}")
        print(f"Owner: {owner.email if owner else '(unknown)'}")

        if args.unseed:
            counts = await wipe(db, site.site_id)
            print(f"Unseeded: {counts}")
            return

        if args.posts is not None:
            await _set_posts_active(db, site, args.posts == "on")
            await db.commit()
            print(f"Posts {'visible' if args.posts == 'on' else 'hidden'} (feed account is_active={args.posts == 'on'}).")
            return

        if args.stage_live:
            await stage_live(db, site)
            print("\n🎬 LIVE-DEMO STAGE READY:")
            print("   - Segments + campaigns pages: EMPTY (press 'Re-run segmentation' on camera)")
            print("   - Social posts: HIDDEN (flip back:  --posts on)")
            print(f"   - Visitors: {len(LEADS)} identified+enriched, untouched")
            print("   - Auto segmentation: dormant (unsegmented count stays under threshold)")
            print("   - Sends blocked for everyone EXCEPT thai_tran (owner inbox = live send target)")
            print("   Restore full pre-built state:  python -m scripts.seed_demo_getbeam --site-id " + site.site_id)
            return

        by_seg = {k: sum(1 for l in LEADS if l['seg'] == k) for k in SEGMENTS}
        print(f"\nPlan: {len(LEADS)} visitors  |  segments {by_seg}  |  3 campaigns (active/draft/approved)")
        print("Campaign emails are pre-marked 'sent' -> a demo 'Send' click contacts NOBODY.")

        if args.dry_run:
            print("\n--dry-run: no writes performed.")
            return

        await seed(db, site)
        print(f"\n✅ Seeded {len(LEADS)} visitors + {len(SEGMENTS)} segments + 3 campaigns into {site.site_id!r}.")
        print("   Reverse anytime:  python -m scripts.seed_demo_getbeam --unseed --site-id " + site.site_id)


if __name__ == "__main__":
    asyncio.run(main())
