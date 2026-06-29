"""Three-layer email validation: format → disposable domain → MX lookup.

Used before persisting emails from form captures and identity resolution
to avoid wasting enrichment credits on bad addresses.
"""

import asyncio
import re

import structlog

logger = structlog.get_logger()

_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}"
    r"[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)

_DISPOSABLE_DOMAINS: set[str] = {
    "10minutemail.com", "33mail.com", "anonbox.net", "binkmail.com",
    "bobmail.info", "bugmenot.com", "bumpymail.com", "burnermail.io",
    "chammy.info", "clickdeal.co", "clrmail.com", "crazymailing.com",
    "deadaddress.com", "despam.it", "devnullmail.com", "dispostable.com",
    "drdrb.net", "dropmail.me", "dumpmail.de", "emailfake.com",
    "emailondeck.com", "emailproxsy.com", "emailsensei.com",
    "emailtemporario.com.br", "fakeinbox.com", "fakemail.fr",
    "fakemailgenerator.com", "filzmail.com", "get2mail.fr",
    "getairmail.com", "getnada.com", "gishpuppy.com", "grr.la",
    "guerrillamail.com", "guerrillamail.de", "guerrillamail.net",
    "guerrillamailblock.com", "harakirimail.com", "hidemail.de",
    "hotpop.com", "hushmail.me", "inboxalias.com", "jetable.org",
    "jourrapide.com", "klzlk.com", "koszmail.pl", "kurzepost.de",
    "lifebyfood.com", "lroid.com", "mailcatch.com", "maildrop.cc",
    "mailexpire.com", "mailforspam.com", "mailinator.com",
    "mailinator.net", "mailinator2.com", "mailmoat.com",
    "mailnator.com", "mailnesia.com", "mailnull.com", "mailshell.com",
    "mailsiphon.com", "mailslite.com", "mailtemp.info", "mailzilla.com",
    "meltmail.com", "mintemail.com", "mobi.web.id", "mohmal.com",
    "mvrht.net", "mytemp.email", "mytrashmail.com", "neverbox.com",
    "nobulk.com", "noclickemail.com", "nogmailspam.info",
    "nomail.xl.cx", "nospam.ze.tc", "notmailinator.com",
    "nowhere.org", "objectmail.com", "obobbo.com", "odaymail.com",
    "onewaymail.com", "owlpic.com", "pjjkp.com", "plexolan.de",
    "pookmail.com", "proxymail.eu", "putthisinyouremail.com",
    "reallymymail.com", "recode.me", "regbypass.com",
    "rhyta.com", "rklips.com", "rmqkr.net", "royal.net",
    "rppkn.com", "safersignup.de", "safetymail.info",
    "sharklasers.com", "shieldedmail.com", "shortmail.net",
    "sify.com", "slaskpost.se", "slipry.net", "slopsbox.com",
    "smellfear.com", "snkmail.com", "sogetthis.com",
    "spam4.me", "spamavert.com", "spambob.net", "spambog.com",
    "spambox.us", "spamcero.com", "spamcorptastic.com",
    "spamcowboy.com", "spamex.com", "spamfighter.cf",
    "spamfree24.com", "spamfree24.de", "spamfree24.eu",
    "spamfree24.info", "spamfree24.net", "spamfree24.org",
    "spamgoes.in", "spamgourmet.com", "spamherelots.com",
    "spamhole.com", "spamify.com", "spaminator.de",
    "spamkill.info", "spaml.com", "spammotel.com",
    "spamobox.com", "spamslicer.com", "spamspot.com",
    "spamthis.co.uk", "spamtrail.com", "speed.1s.fr",
    "suremail.info", "teleworm.us", "temp-mail.org",
    "temp-mail.ru", "tempail.com", "tempalias.com",
    "tempe4mail.com", "tempemail.co.za", "tempemail.net",
    "tempinbox.com", "tempmail.eu", "tempmail.it",
    "tempmail2.com", "tempmaildemo.com", "tempmailer.com",
    "tempomail.fr", "temporaryemail.net", "temporaryemail.us",
    "temporaryforwarding.com", "temporaryinbox.com",
    "temporarymailaddress.com", "thankmail.com", "thankyou2010.com",
    "thisisnotmyrealemail.com", "throwam.com", "throwawayemailaddress.com",
    "tmail.ws", "tmailinator.com", "toiea.com", "tradermail.info",
    "trash-mail.at", "trash-mail.com", "trash-mail.de", "trash2009.com",
    "trashmail.at", "trashmail.com", "trashmail.io", "trashmail.me",
    "trashmail.net", "trashmail.org", "trashymail.com",
    "trbvm.com", "turual.com", "twinmail.de",
    "tyldd.com", "uggsrock.com", "upliftnow.com", "uplipht.com",
    "venompen.com", "veryreallyfakemail.com", "viditag.com",
    "viewcastmedia.com", "viewcastmedia.net", "vomoto.com",
    "vubby.com", "webemail.me", "weg-werf-email.de",
    "wegwerfadresse.de", "wegwerfemail.com", "wegwerfmail.de",
    "wegwerfmail.net", "wegwerfmail.org", "wh4f.org",
    "whyspam.me", "wikidocuslice.com", "willhackforfood.biz",
    "willselfdestruct.com", "wuzup.net", "wuzupmail.net",
    "wwwnew.eu", "xagloo.com", "xemaps.com", "xents.com",
    "xjoi.com", "xmaily.com", "xoxy.net", "yep.it",
    "yogamaven.com", "yopmail.com", "yopmail.fr", "yopmail.net",
    "yourdomain.com", "ypmail.webarnak.fr.eu.org",
    "yuurok.com", "zehnminutenmail.de", "zippymail.info",
    "zoaxe.com", "zoemail.org",
}

_MX_CACHE_PREFIX = "mx_valid:"
_MX_CACHE_TTL = 7 * 24 * 3600


async def validate_email(email: str) -> tuple[bool, str]:
    """Validate email: format → disposable domain → MX record.

    Returns (is_valid, reason). Reason is "" for valid emails.
    """
    if not email or not isinstance(email, str):
        return False, "empty"

    email = email.strip().lower()

    if not _EMAIL_RE.match(email):
        return False, "invalid_format"

    parts = email.split("@")
    if len(parts) != 2:
        return False, "invalid_format"

    domain = parts[1]

    if domain in _DISPOSABLE_DOMAINS:
        return False, "disposable_domain"

    mx_valid = await _check_mx(domain)
    if not mx_valid:
        return False, "no_mx_record"

    return True, ""


async def _check_mx(domain: str) -> bool:
    """Check domain has valid MX records. Cached in Redis 7 days."""
    try:
        from apps.api.services.redis_client import get_redis
        redis = get_redis()
        cached = await redis.get(f"{_MX_CACHE_PREFIX}{domain}")
        if cached is not None:
            return cached == "1"
    except Exception:
        pass

    def _resolve_mx() -> bool:
        import dns.resolver

        try:
            return len(dns.resolver.resolve(domain, "MX")) > 0
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            # No MX record — many small domains accept mail on their A/AAAA host
            # (implicit MX), so fall back to a plain address lookup.
            try:
                dns.resolver.resolve(domain, "A")
                return True
            except Exception:
                return False
        except Exception:
            return False

    try:
        loop = asyncio.get_event_loop()
        valid = await asyncio.wait_for(
            loop.run_in_executor(None, _resolve_mx),
            timeout=5.0,
        )
    except Exception:
        valid = False

    try:
        from apps.api.services.redis_client import get_redis
        redis = get_redis()
        await redis.setex(f"{_MX_CACHE_PREFIX}{domain}", _MX_CACHE_TTL, "1" if valid else "0")
    except Exception:
        pass

    return valid
