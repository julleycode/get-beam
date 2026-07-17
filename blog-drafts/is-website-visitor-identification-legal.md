---
title: Is Website Visitor Identification Legal? GDPR & CCPA
meta_description: Is website visitor identification legal? Yes, with conditions. The GDPR and CCPA rules for company and person-level tracking, plus a compliance checklist.
slug: is-website-visitor-identification-legal
tags: [visitor-identification, b2b]
target_keyword: is website visitor identification legal
cluster: C14 (compliance and legal)
internal_links: [/blog/website-visitor-identification-turn-anonymous-traffic-into-leads, /blog/person-level-visitor-identification, /blog/identify-anonymous-website-visitors, /onboarding]
status: draft
---

# Is Website Visitor Identification Legal? GDPR & CCPA

Short answer: yes, website visitor identification is legal, and the conditions depend on two things: what you identify (companies or people) and where your visitors are (EU, US, or elsewhere). Get those two variables right and this is a well-trodden, defensible practice used by thousands of companies. Get them wrong and you're processing personal data without a lawful basis, which is exactly the kind of unforced error regulators enjoy.

This guide covers the rules as they stand in 2026, in plain language. One disclaimer up front: this is an explainer, not legal advice. For deployment decisions in your specific situation, talk to a lawyer.

## The Distinction That Decides Everything: Companies vs People

Privacy law protects natural persons, not legal entities. That single fact splits visitor identification into two very different regimes.

**Company-level identification** (reverse IP lookup revealing that "Acme GmbH visited your pricing page") processes data about an organization. Under GDPR, this is broadly permitted on the lawful basis of legitimate interest (Article 6(1)(f)), because a company is not a natural person. This is why company-level tools operate freely across Europe, and why several of them are European companies themselves. Caveats exist: an IP address can be personal data when it points at an individual, sole traders blur the line, and you still need disclosure in your privacy policy plus a documented legitimate interest assessment.

**Person-level identification** (resolving the actual individual: name, role, profiles) is unambiguously processing personal data. For EU visitors, that requires a lawful basis, and in practice that means consent collected before the identification script fires: a consent management platform, not a banner that ignores the answer. For US visitors, the default flips: collection is permitted, with disclosure and opt-out obligations instead of prior consent. The technical difference between the two levels is explained in our [person-level identification guide](https://getbeam.fyi/blog/person-level-visitor-identification).

## GDPR: What EU Traffic Requires

Four practical obligations cover most deployments. You need a lawful basis: legitimate interest can carry company-level identification, while person-level identification of EU visitors effectively requires consent. You need transparency: your privacy policy must disclose what's collected, the lawful basis, the third-party processors involved, retention periods, and data subject rights. You need consent mechanics that actually work: non-essential tracking blocked until opt-in, with regional rules applied by geography if you treat EU and US traffic differently. And you need paperwork: Article 30 records of processing, a Data Processing Agreement with your vendor, and Standard Contractual Clauses if data crosses borders.

If your product sells only to the US and your EU traffic is incidental, a common pattern is restricting person-level identification to US traffic and letting EU sessions pass unidentified or company-level only. Several tools implement exactly this behavior regionally.

## CCPA and CPRA: What California Requires

California's model is disclosure-and-opt-out rather than prior consent. You may collect by default, but you must give notice at collection, maintain a "Do Not Sell or Share My Personal Information" mechanism, honor Global Privacy Control signals, and respect deletion requests. Since identified visitor data shared with ad platforms can qualify as "sharing," the opt-out needs to genuinely stop the flow, not just hide the link. The obligation sits with you as the site owner; your vendor's compliance page is a starting point, not a substitute.

## The Vendor Questions That Separate Clean From Sketchy

Whatever tool you evaluate, five questions expose its compliance posture. Where does the identity data come from, and is it consented at the source? Does the tool support consent-mode integration (holding identification until opt-in) and regional behavior? Will the vendor sign a DPA and provide subprocessor documentation? Can it honor deletion and opt-out requests end to end? And does it resell your visitor data (the only acceptable answer is no)?

For the record, Beam's posture on these: GDPR and CCPA compliant, no fake profiles, no scraping of data you couldn't see yourself, outreach sent manually from your own accounts with zero automation on your side, and your visitor data is never sold or shared. The practical deployment flow, consent banner included, is in our [setup guide](https://getbeam.fyi/blog/get-started-with-visitor-identification-b2b-setup-guide).

## Your Pre-Launch Compliance Checklist

Before the script goes live: decide your identification level per region (person-level US, company-level or consented EU is the common pattern), update the privacy policy with what, why, who, and how long, deploy a consent banner that actually blocks scripts pre-consent for EU visitors, add the CCPA opt-out link, sign the vendor DPA, and document your legitimate interest assessment if you rely on it. An afternoon of setup, and the whole topic stops being scary. The broader context of what identification can and can't do sits in our [pillar guide](https://getbeam.fyi/blog/website-visitor-identification-turn-anonymous-traffic-into-leads).

## FAQ

**Is it legal to identify companies visiting my website?**
Generally yes, including in the EU, where company-level identification typically runs on legitimate interest since companies aren't natural persons. You still need privacy policy disclosure and a documented assessment.

**Is it legal to identify individual website visitors?**
In the US, yes, with CCPA disclosure and opt-out obligations. For EU visitors, person-level identification requires consent before the script runs. Many teams restrict person-level identification to US traffic for this reason.

**Do I need a cookie banner for visitor identification?**
For EU traffic, yes if you identify individuals or use non-essential cookies: consent must come first. For US-only traffic, disclosure and opt-out generally suffice under CCPA.

**Who is responsible for compliance, me or the tool vendor?**
You, as the data controller. The vendor is your processor: it must support compliance (DPA, deletion, consent modes), but the lawful basis, disclosures, and regional decisions are the site owner's responsibility.

---

**compliant and effective aren't opposites.** see who's on your site, the clean way. [get started free →](https://getbeam.fyi/onboarding)
