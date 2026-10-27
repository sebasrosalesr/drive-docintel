from conftest import canned_response, extraction

from docintel import pii
from docintel.pipeline import process_bytes

DL_OCR = """CALIFORNIA   DRIVER LICENSE
DL 1234567   CLASS C   EXP 08/31/2029
LN DOE  FN JANE
123 ANY STREET, ANYTOWN CA 90000
DOB 08/31/1985   RSTR NONE   SEX F   HAIR BRN   EYES BRN   HGT 5'-06"   WGT 130 lb
ISS 08/31/2024   DONOR   VETERAN
"""


def test_driver_licence_is_identity():
    s = pii.screen(DL_OCR, "scan.jpg")
    assert s.identity == "driver" and s.identity_label == "driver's licence" and s.scores["driver"] >= 4


def test_long_document_mentioning_a_licence_is_not_identity():
    text = ("Onboarding checklist. Please attach a copy of your driver's license or passport. " * 120)
    s = pii.screen(text, "onboarding.pdf")
    assert s.identity == ""


def test_redaction_masks_identifiers_and_keeps_text():
    text = "Account statement. SSN: 123-45-6789. Card 4111 1111 1111 1111 on file. Routing 021000021, Account No. 0012345678901. Invoice 2024-10001 total $60.90."
    out, counts = pii.redact(text)
    assert "[REDACTED SSN]" in out and "[CARD ••••1111]" in out and "[ROUTING ••••0021]" in out and "[ACCOUNT ••••8901]" in out
    assert "2024-10001" in out and "$60.90" in out
    assert counts == {"ssn": 1, "card": 1, "routing": 1, "account": 1}


def test_pipeline_rejects_identity_document_without_calling_the_model(session):
    calls = []
    doc = process_bytes(session, name="mock_dl.txt", mime="text/plain", data=DL_OCR.encode(), transport=lambda b: calls.append(b) or canned_response(extraction()), force=True)
    assert doc.status == "rejected" and calls == [] and doc.raw_text == "" and "driver" in doc.error
    from docintel.pipeline import load_blob
    assert load_blob(doc.sha256) is None


def test_pipeline_sends_redacted_text_when_identifiers_present(session):
    seen = {}

    def transport(body):
        seen.update(body)
        return canned_response(extraction(doc_type="letter"))

    data = b"Quarterly statement for Jane Doe\nSSN 123-45-6789\nEnding balance $1,000.00\n"
    doc = process_bytes(session, name="stmt.txt", mime="text/plain", data=data, transport=transport, force=True)
    sent = seen["messages"][1]["content"][0]["text"]
    assert "123-45-6789" not in sent and "[REDACTED SSN]" in sent
    assert "123-45-6789" not in doc.raw_text and doc.status == "done"
    assert any(f["code"] == "pii_redacted" for f in doc.validation_json["flags"])
