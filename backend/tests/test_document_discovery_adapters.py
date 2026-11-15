"""Phase 12B — adapter-level tests. No live network calls: httpx responses are
mocked via a fake client / monkeypatched _get. The real, live-verified parse (an
actual cached screener.in TCS page, confirmed during this phase's development to
produce correct candidates) is documented in docs/FINN_PHASE_12B_REPORT.md, not
re-fetched here.
"""

import httpx
import pytest

from app.services.document_discovery.ir_website_adapter import IRWebsiteSourceAdapter
from app.services.document_discovery.screener_adapter import ScreenerSourceAdapter

SCREENER_HTML = """
<html><head><title>Tata Consultancy Services Ltd share price | About TCS</title></head>
<body>
  <div class="documents annual-reports flex-column">
    <h3>Annual reports</h3>
    <ul class="list-links">
      <li><a href="https://www.bseindia.com/pdf/ar2026.pdf">Annual Report 2026</a></li>
      <li><a href="https://www.bseindia.com/pdf/ar2025.pdf">Annual Report 2025</a></li>
    </ul>
  </div>
  <div class="documents concalls flex-column">
    <h3>Concalls</h3>
    <ul class="list-links">
      <li class="flex flex-gap-8">
        <div>Oct 2026</div>
        <a href="https://www.bseindia.com/pdf/transcript_oct26.pdf" title="Raw Transcript">Transcript</a>
        <a href="https://www.tcs.com/pdf/ppt_oct26.pdf">PPT</a>
      </li>
      <li class="flex flex-gap-8">
        <div>Jul 2026</div>
        <a href="https://www.bseindia.com/pdf/transcript_jul26.pdf" title="Raw Transcript">Transcript</a>
      </li>
    </ul>
  </div>
</body></html>
"""

WRONG_COMPANY_HTML = """
<html><head><title>Infosys Ltd share price | About Infosys</title></head>
<body><div class="documents annual-reports flex-column">
<a href="https://x.com/ar.pdf">Annual Report 2026</a>
</div></body></html>
"""


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


class _FakeClient:
    def __init__(self, responses: dict[str, _FakeResponse] | None = None, exc: Exception | None = None):
        self.responses = responses or {}
        self.exc = exc
        self.calls: list[str] = []

    def get(self, url: str) -> _FakeResponse:
        self.calls.append(url)
        if self.exc is not None:
            raise self.exc
        return self.responses.get(url, _FakeResponse(404))

    def close(self):
        pass


class TestScreenerAdapter:
    def test_discovers_annual_reports_and_concalls_with_identity_verified(self):
        url = "https://www.screener.in/company/TCS/consolidated/"
        client = _FakeClient({url: _FakeResponse(200, SCREENER_HTML)})
        adapter = ScreenerSourceAdapter(client=client)

        result = adapter.check("TCS", "Tata Consultancy Services Ltd")

        assert result.ok is True
        assert result.identity_verified is True
        doc_types = {c.doc_type for c in result.candidates}
        assert doc_types == {"annual_report", "concall_transcript", "investor_presentation"}
        annual = [c for c in result.candidates if c.doc_type == "annual_report"]
        assert {c.reporting_period for c in annual} == {"FY26", "FY25"}

    def test_wrong_company_identity_is_rejected_not_trusted(self):
        """A URL containing the right ticker but whose PAGE describes a
        different company must never be trusted — the core 'don't assign by
        URL alone' requirement."""
        url = "https://www.screener.in/company/TCS/consolidated/"
        client = _FakeClient({url: _FakeResponse(200, WRONG_COMPANY_HTML)})
        adapter = ScreenerSourceAdapter(client=client)

        result = adapter.check("TCS", "Tata Consultancy Services Ltd")

        assert result.ok is True
        assert result.identity_verified is False
        assert result.candidates == []

    def test_tmpv_and_tmcv_are_never_confused(self):
        """Two distinct, similarly-named companies must each only match their
        OWN expected name — simulates the real TMPV/TMCV separation risk."""
        tmpv_html = SCREENER_HTML.replace(
            "Tata Consultancy Services Ltd share price | About TCS",
            "Tata Motors Passenger Vehicles Ltd share price | About Tata Motors PVeh",
        )
        url = "https://www.screener.in/company/TMPV/consolidated/"
        client = _FakeClient({url: _FakeResponse(200, tmpv_html)})
        adapter = ScreenerSourceAdapter(client=client)

        result_correct = adapter.check("TMPV", "Tata Motors Passenger Vehicles Ltd")
        assert result_correct.identity_verified is True

        result_wrong = adapter.check("TMPV", "Tata Motors Commercial Vehicles Ltd")
        assert result_wrong.identity_verified is False

    def test_timeout_is_reported_as_a_clean_failure(self):
        client = _FakeClient(exc=httpx.TimeoutException("timed out"))
        adapter = ScreenerSourceAdapter(client=client)
        result = adapter.check("TCS", "Tata Consultancy Services Ltd")
        assert result.ok is False
        assert "Timed out" in result.error

    def test_404_falls_back_to_standalone_url_then_fails_cleanly(self):
        client = _FakeClient({})  # both URLs 404 by default
        adapter = ScreenerSourceAdapter(client=client)
        result = adapter.check("NOTREAL", "Not Real Ltd")
        assert result.ok is False
        assert len(client.calls) == 2  # tried consolidated, then standalone


class TestIRWebsiteAdapter:
    def test_no_seed_url_is_reported_honestly_not_guessed(self):
        adapter = IRWebsiteSourceAdapter()
        result = adapter.check("TCS", "Tata Consultancy Services Ltd", seed_url=None)
        assert result.ok is False
        assert "No verified investor_relations_url" in result.error

    def test_discovers_pdfs_on_own_domain_and_classifies_by_keyword(self):
        html = """
        <html><head><title>HDFC Bank Investor Relations</title></head>
        <body>
          <a href="/pdf/annual-report-2026.pdf">Annual Report</a>
          <a href="/pdf/q2fy27-earnings-presentation.pdf">Earnings Presentation</a>
          <a href="/pdf/unrelated-policy.pdf">Deposit Policy</a>
        </body></html>
        """
        url = "https://www.hdfcbank.com/ir"
        client = _FakeClient({url: _FakeResponse(200, html)})
        adapter = IRWebsiteSourceAdapter(client=client)

        result = adapter.check("HDFCBANK", "HDFC Bank Ltd", seed_url=url)
        assert result.ok is True
        assert result.identity_verified is True
        doc_types = {c.doc_type for c in result.candidates}
        assert doc_types == {"annual_report", "investor_presentation"}  # the unrelated policy PDF is correctly skipped

    def test_off_domain_pdf_links_are_not_auto_trusted(self):
        html = """
        <html><head><title>HDFC Bank Investor Relations</title></head>
        <body><a href="https://www.bseindia.com/some/annual-report.pdf">Annual Report (BSE mirror)</a></body></html>
        """
        url = "https://www.hdfcbank.com/ir"
        client = _FakeClient({url: _FakeResponse(200, html)})
        adapter = IRWebsiteSourceAdapter(client=client)
        result = adapter.check("HDFCBANK", "HDFC Bank Ltd", seed_url=url)
        assert result.candidates == []
