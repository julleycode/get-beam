# KG-3: WS-B corpus is derived-label, not ground truth

Owner: visitors-identity / ip-org-quality-pack (WS-B)
Priority: P2

A corporate email domain is strong but imperfect evidence of the employer behind an IP
(contractors, personal-domain founders, shared offices). The free-mail exclusion set is a
JUDGMENT list = `content_reader._GENERIC_DOMAINS` + a benchmark addendum − {linkedin.com,
x.com}; any consumer-mail domain still leaking through carries a fabricated expected_org
that can never match, biasing the headline number DOWNWARD. Additionally, the
datacenter/CDN headline exclusion is produced BY THE SYSTEM UNDER TEST, systematically
removing a class of the pipeline own misclassifications from the headline number. Gate G8
proves the measurement ran, not that its labels are perfect. Report states both directions.
