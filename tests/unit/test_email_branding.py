"""Unit tests for the shared "Powered by Beam" email footer."""

from apps.api.services.email_branding import BEAM_FOOTER_URL, beam_email_footer


class TestBeamEmailFooter:
    def test_footer_links_to_landing_with_utm(self):
        html = beam_email_footer()
        assert "getbeam.fyi" in html
        assert "utm_source=email_footer" in BEAM_FOOTER_URL
        assert "utm_medium=email" in BEAM_FOOTER_URL
        assert "utm_campaign=powered_by" in BEAM_FOOTER_URL
        assert BEAM_FOOTER_URL in html

    def test_footer_mentions_beam(self):
        assert "Powered by" in beam_email_footer()
        assert "Beam" in beam_email_footer()
