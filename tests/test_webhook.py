import hashlib
import hmac
import pytest

from byjg_docs_mcp.webhook import _touches_docs, verify_signature

SECRET = "s3cr3t"


def sign(payload: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


class TestSignature:
    def test_valid_signature_is_accepted(self):
        body = b'{"ref":"refs/heads/master"}'
        assert verify_signature(body, sign(body), SECRET)

    def test_signature_from_a_different_secret_is_rejected(self):
        body = b'{"ref":"refs/heads/master"}'
        assert not verify_signature(body, sign(body, "wrong"), SECRET)

    def test_tampered_payload_is_rejected(self):
        body = b'{"ref":"refs/heads/master"}'
        header = sign(body)
        assert not verify_signature(body + b" ", header, SECRET)

    @pytest.mark.parametrize("header", [None, "", "deadbeef", "sha1=abc", "sha256=", "sha256=zz"])
    def test_missing_or_malformed_headers_are_rejected(self, header):
        assert not verify_signature(b"{}", header, SECRET)


class TestDocsFilter:
    def test_push_touching_docs_triggers(self):
        payload = {"commits": [{"added": [], "modified": ["docs/php/micro-orm/a.md"], "removed": []}]}
        assert _touches_docs(payload, "docs/")

    def test_deleted_doc_triggers(self):
        payload = {"commits": [{"added": [], "modified": [], "removed": ["docs/php/old.md"]}]}
        assert _touches_docs(payload, "docs/")

    def test_push_touching_only_build_files_is_ignored(self):
        payload = {"commits": [{"added": [], "modified": ["package-lock.json"], "removed": []}]}
        assert not _touches_docs(payload, "docs/")

    def test_push_with_no_commits_is_ignored(self):
        assert not _touches_docs({"commits": []}, "docs/")
        assert not _touches_docs({}, "docs/")
