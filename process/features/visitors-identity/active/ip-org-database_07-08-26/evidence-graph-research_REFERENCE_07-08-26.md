# Evidence-Graph Research Reference — IP-to-Company + Non-Cookie Identity

Date captured: 2026-08-07
Source: user-supplied research synthesis (verbatim below, unedited)
Consumed by: Phase 3 plan (`ip-org-phase-3-evidence-graph_PLAN_07-08-26.md`)

Orchestrator assessment at capture time (repo mapping):
- Core hit: current `ip_org_prefixes` is the "flat enrichment table" this doc critiques; CAIDA pfx2as is BGP-derived so our `org_name` is ROUTE_ORIGIN, not REGISTERED_HOLDER. Transit/hosting announce on behalf of customers → wrong-entity rows beyond what eyeball/datacenter/cdn tagging catches.
- Cheap adoption path: `company_graph` already has `(ip, source)` multi-source + confidence-desc read = primitive evidence fusion in place. Add RIR delegated-stats (REGISTERED_HOLDER) + RPKI ROA as sources 2-3; agreement raises confidence, disagreement lowers. Add `relationship_type` + `valid_from`/`valid_to` to `ip_org_prefixes`.
- Already aligned (no action): HMAC keyed pseudonyms (PII blind index pattern — better than the plan's original "SHA-256"), first-party identity hierarchy (svid 0.90 > graph 0.85 > fp3 0.80 > fp2 0.75), corroborate-only identity_signals, bidstream rejected, anti-bot brand.
- Open product decision (identity side, NOT Phase 3 scope): fp-only cross-tenant graph match currently creates identified at 0.85; doc argues fp should not solely assign a named person → consider demoting fp-only to `candidate` until corroborated.
- ASINT-style org-family resolution + PSI/clean-room CRM matching: acknowledged, deferred to later phases (expensive; CRM connectors exist as future mount point).

---

## Verbatim source

The most important academic breakthrough is that IP-to-company resolution is no longer treated as a simple WHOIS lookup. Modern systems model the Internet as a temporal, multi-evidence graph involving routing control, IP registration, RPKI, DNS, hosting relationships, organization hierarchies, and web evidence.

For non-cookie tracking, the major shift is different: the field is moving away from hidden person-level re-identification toward first-party authentication, probabilistic identity graphs, privacy-preserving matching, and browser-mediated aggregate APIs. Browser fingerprinting can identify or link devices, but it does not reliably establish a person or company identity and creates serious privacy risks.

### 1. IP-to-Company: Beyond WHOIS

#### 1.1 The core conceptual error

A traditional lookup assumes:

```
IP address → ASN → registered organization → company
```

This is often wrong because the organization that: owns an IP allocation, announces a route, operates the network, leases infrastructure, hosts a customer, or appears in reverse DNS may be different entities.

For example:

```
IP prefix
  ├── RIR registration: Company A
  ├── BGP origin: Transit provider B
  ├── datacenter operator: Company C
  ├── customer: Company D
  └── reverse DNS: cloud-provider hostname
```

The correct target is therefore not merely "registered owner," but a set of distinct relationships:

```
registered_holder
routing_origin
operational_operator
infrastructure_provider
likely_end_customer
```

This distinction is central to recent work such as Prefix2Org, which argues that ASN-based mapping is inaccurate because autonomous systems frequently announce prefixes on behalf of customers. The project combines WHOIS, BGP routing data, and RPKI certificates to map prefixes according to operational rights.

#### 1.2 Prefix2Org

Prefix2Org contributions: mapping BGP prefixes directly to organizations rather than stopping at ASN; separating different forms of operational control; combining RIR/WHOIS records, routing observations, and RPKI; producing a public dataset covering almost all publicly announced prefixes; modeling the operator/customer relationship.

The database should not look like `ip_range → company_name`. It should look like:

```
prefix | organization | relationship_type | evidence_source | confidence | valid_from | valid_to
```

Relationship taxonomy:

| Relationship | Meaning |
|---|---|
| REGISTERED_HOLDER | Entity recorded by the relevant RIR |
| ROUTE_ORIGIN | ASN currently originating the prefix |
| RPKI_AUTHORIZER | Entity authorized through ROA data |
| NETWORK_OPERATOR | Entity operating or announcing the network |
| INFRASTRUCTURE_PROVIDER | Cloud, hosting, CDN, or datacenter provider |
| LIKELY_CUSTOMER | Inferred end organization |
| REVERSE_DNS_OWNER | Entity suggested by PTR/rDNS evidence |

This structure answers distinct product questions: "Who owns this address space?" / "Who operates this network?" / "Is this traffic from a corporate network?" / "Is this likely cloud infrastructure?" / "Which customer may be behind this hosting provider?" — not the same query.

#### 1.3 ASINT: organization families and web evidence

ASINT extends AS-to-organization mapping by combining bulk registry data with unstructured sources (company websites, Wikipedia, news) using retrieval-augmented generation and entity-resolution inside an evidence-constrained pipeline:

```
registry records + PeeringDB + company websites + public org info + name normalization + parent/subsidiary rules → organization family graph
```

ASINT reports mapping 111,470 ASNs to 81,233 organization families. Valuable for: rebrands, subsidiaries, regional operating companies, parent relationships, telecom groups, cloud/hosting brands, multi-entity organizations.

Correct architecture: `ASN → legal organization → organization family → brand → corporate domain`. Do not collapse these into one canonical company name.

### 2. The Evidence Graph Architecture

#### 2.1 Graph model

```
IP
 └── Prefix
      ├── originated_by → ASN
      ├── authorized_by → RPKI entity
      ├── registered_to → RIR organization
      ├── reverse_dns → hostname
      ├── hosted_by → provider
      ├── observed_with → domain/certificate
      └── inferred_customer → organization
```

Each edge carries: source, observed_at, valid_from, valid_to, confidence, evidence_uri, method.

#### 2.2 Evidence is time-aware

Every assertion has temporal validity (prefix P → Company A Jan–Mar; → Provider B from Apr). Needed for: historical attribution, cloud-migration detection, dynamic-reassignment vs stable ownership, stale-match prevention, false-positive investigation.

#### 2.3 Evidence fusion

Score a company hypothesis from independent signals: P(c | e1..en). Practical linear model:

S(c) = w_r·R + w_p·P + w_d·D + w_t·T + w_x·X − w_s·S

R: RIR registration consistency; P: RPKI consistency; D: DNS/rDNS; T: TLS/domain; X: historical/cross-source agreement; S: shared-hosting/ISP ambiguity penalty.

Output contains candidate AND evidence AND uncertainty:

```json
{
  "organization": "Example Corp",
  "classification": "likely_operational_customer",
  "confidence": 0.78,
  "evidence": ["BGP origin consistency", "reverse DNS domain match", "TLS certificate association", "historical stability"],
  "uncertainty": ["prefix partially hosted by third-party provider"]
}
```

### 3. Non-Cookie Tracking: What Actually Works

#### 3.1 First-party identity is the strongest replacement

Identity hierarchy:

| Signal | Identifies | Reliability |
|---|---|---|
| Authenticated SSO subject | Person/account | Very high |
| Verified email-link event | Person/browser relationship | High |
| Customer CRM identifier | Customer-known person/account | High |
| First-party account cookie | Browser within one site | Medium-high |
| Server-side session ID | Session/browser continuity | Medium |
| IP + network evidence | Network/account hypothesis | Low-medium |
| Browser fingerprint | Device/browser similarity | Variable |
| Page behavior alone | Intent or cohort | Not person identity |

A cookie never truly identified a person; it identified a browser with some probability. Post-cookie makes this uncertainty visible rather than eliminating it.

#### 3.2 Probabilistic identity graphs

Identifiers as nodes, observed relationships as weighted edges. Critical principle: **confidence belongs on edges, not only the final person record.** Distinguish: deterministic edge (verified login), strong first-party edge (signed email link), medium edge (repeated same-site behavior), weak edge (IP/UA/time correlation), negative edge (VPN, shared network, conflicting identity). Do not let a weak edge transitively generate a high-confidence person match.

#### 3.3 Browser fingerprinting

Capable of linking browser configurations without cookies (UA, screen, timezone, language, graphics stack, canvas/WebGL, APIs, network properties). Three limitations: identifies browser/device not person; shared devices + changing environments cause collisions/instability; increasingly restricted as privacy-sensitive tracking. For B2B: use for fraud/bot detection, session continuity, duplicate suppression, aggregate modeling. Not sole basis for assigning a named employee.

### 4. Privacy-Preserving Alternatives

#### 4.1 Private Set Intersection

PSI lets customer CRM and anonymous-event sets compute overlap without exposing full datasets. In production use keyed pseudonyms `HMAC(secret_key, normalized_email)` — plain SHA-256 email hashes are dictionary-enumerable. Useful for: account-list matching, customer-owned visitor identification, CRM enrichment, suppression lists, consented campaign measurement. Not a method for discovering a person from an arbitrary anonymous IP.

#### 4.2 Clean rooms and controlled joins

customer identity data + behavioral events → controlled match → permitted aggregate output (account-level visit counts, matched audience size, buying-stage distribution, conversion attribution, role-level aggregates). Prevent arbitrary person-level export unless customer supplied identity and authorized use.

#### 4.3 Browser-mediated privacy APIs

Privacy Sandbox: Attribution Reporting, Protected Audience, Topics, Private State Tokens, FedCM, CHIPS, Storage Access API. Relevant for advertising/attribution platforms; less useful for named B2B visitor identification because they deliberately avoid exposing individual identity.

### 5. What Not to Build

- Hidden cookie-sync iframes — cannot obtain UID2/MAID/raw identity without participating partners + consented/authenticated identifiers.
- "Raw identity dumps" (MAID → email → LinkedIn) — extremely sensitive personal data; treat cheap-and-legal claims with skepticism.
- LinkedIn candidate inference (company + page + employee list → likely individual) — candidate-ranking, not identity resolution; label explicitly as probabilistic account intelligence.
- Long-lived fingerprinting surviving cookie deletion — covert identifier; compliance/reputational/browser-blocking risk (EDPB guidance covers terminal-storage-access technologies beyond cookies).

### 6. Recommended Research Program

- **Phase 1 — network truth layer:** RIR/WHOIS + BGP + RPKI + PeeringDB + rDNS + TLS certs + ASN history + hosting classification → IP/prefix → operational organization graph. Benchmark against manually verified enterprise networks + known cloud providers.
- **Phase 2 — organization resolution:** legal-name normalization, parent/subsidiary clustering, rebrand detection, domain-to-org mapping, org-family resolution, evidence-backed LLM classification. ASINT as baseline, not ground truth.
- **Phase 3 — account-level visitor intelligence:** network type, corporate-vs-residential probability, shared-hosting risk, repeated account activity, content intent, temporal stability, CRM overlap. Return account + intent + confidence + evidence + uncertainty. No named person without a verified identity event.
- **Phase 4 — verified person layer:** SSO, verified email links, CRM integrations, signed campaign URLs, customer-side HMAC matching, consented first-party SDK, clean room. Durable moat: strongest signals generated through product + customer relationships, not copied from public IP databases.

### Final Assessment

Strongest opportunity = Prefix2Org-style prefix-to-organization mapping (separating registration / routing / operational control) + organization-family resolution (ASINT-style) + temporal evidence graphs + probabilistic identity graphs with per-edge confidence + privacy-preserving customer-side matching + browser-mediated measurement.

The practical breakthrough is NOT `anonymous IP → exact employee`. It is:

```
network observation
→ evidence-backed organization hypothesis
→ account-level intent
→ customer-controlled identity match
→ verified person only when authorized
```

Technically stronger, easier to defend, and more likely to survive browser and privacy changes than zero-click deanonymization.
