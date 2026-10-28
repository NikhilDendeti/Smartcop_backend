import hashlib
import os
import socket
import tempfile
import threading
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from core.models import AuditLog
from core.scanning import ClamdScanner, UnconfiguredScanner
from core.storage import LocalFileStorage, S3Storage
from core.test_rbac import RBACTestCase
from core.testing import auth_headers
from police.models import MagistrateApproval
from users.models import EvidenceFile

PHOTO = b"\xff\xd8\xff" + b"jpeg-bytes" * 50


class CleanScanner:
    def scan(self, open_file):
        return "clean"


class InfectedScanner:
    def scan(self, open_file):
        return "infected"


class EvidenceTestCase(RBACTestCase):
    def setUp(self):
        super().setUp()
        self.storage_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.storage_dir.cleanup)
        settings_override = override_settings(EVIDENCE_ROOT=self.storage_dir.name, EVIDENCE_ALLOW_UNSCANNED=False)
        settings_override.enable()
        self.addCleanup(settings_override.disable)

    def announce(self, user, complaint=None, content=PHOTO, name="photo.jpg", content_type="image/jpeg", **overrides):
        body = {
            "filename": name,
            "content_type": content_type,
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            **overrides,
        }
        return self.post(user, f"/api/v1/complaints/{(complaint or self.complaint).pk}/evidence-files/", body)

    def send(self, user, file_id, content=PHOTO):
        return self.client.put(
            f"/api/v1/evidence-files/{file_id}/content/", data=content,
            content_type="application/octet-stream", **auth_headers(user),
        )

    def download(self, user, file_id):
        response = self.get(user, f"/api/v1/evidence-files/{file_id}/download/")
        if response.streaming:
            # Reading the stream lets the test client close it correctly, which also releases the
            # file handle before the temporary folder is removed (matters on Windows).
            response.body_bytes = b"".join(response.streaming_content)
        return response

    def complete(self, user, file_id):
        return self.post(user, f"/api/v1/evidence-files/{file_id}/complete/", {})

    def upload_fully(self, user, scanner=CleanScanner, complaint=None, content=PHOTO):
        file_id = self.announce(user, complaint, content).json()["file_id"]
        self.send(user, file_id, content)
        with patch("users.evidence_api.get_scanner", return_value=scanner()):
            self.complete(user, file_id)
        return file_id


class UploadFlowTests(EvidenceTestCase):
    def test_a_citizen_can_upload_verify_and_download_their_evidence(self):
        announced = self.announce(self.citizen)
        self.assertEqual(announced.status_code, 201)
        file_id = announced.json()["file_id"]
        self.assertEqual(announced.json()["upload"]["url"], f"/api/v1/evidence-files/{file_id}/content/")
        self.assertFalse(announced.json()["uploaded"])

        self.assertEqual(self.send(self.citizen, file_id).status_code, 204)
        with patch("users.evidence_api.get_scanner", return_value=CleanScanner()):
            done = self.complete(self.citizen, file_id).json()
        self.assertTrue(done["uploaded"])
        self.assertEqual(done["scan_status"], "clean")

        download = self.download(self.citizen, file_id)
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.body_bytes, PHOTO)
        self.assertIn("attachment", download["Content-Disposition"])
        self.assertEqual(download["X-Content-Type-Options"], "nosniff")

    def test_files_are_listed_with_their_status(self):
        file_id = self.upload_fully(self.citizen)
        listing = self.get(self.si, f"/api/v1/complaints/{self.complaint.pk}/evidence-files/").json()
        self.assertEqual([item["file_id"] for item in listing], [file_id])
        self.assertTrue(listing[0]["uploaded"])

    def test_officers_in_scope_can_add_and_read_evidence_but_not_outsiders(self):
        self.assertEqual(self.announce(self.si).status_code, 201)
        self.assertEqual(self.announce(self.si_b).status_code, 404)
        self.assertEqual(self.announce(self.other_citizen).status_code, 404)
        self.assertEqual(self.announce(self.admin).status_code, 403)
        self.assertEqual(self.announce(self.magistrate).status_code, 404)  # not routed to them
        MagistrateApproval.objects.create(complaint=self.complaint, marked_by=self.si)
        self.assertEqual(self.announce(self.magistrate).status_code, 403)  # routed: may read, not add

    def test_storage_keys_never_contain_the_file_name(self):
        file_id = self.announce(self.citizen, name="../../etc/passwd").json()["file_id"]
        record = EvidenceFile.objects.get(pk=file_id)
        self.assertNotIn("passwd", record.storage_key)
        self.assertNotIn("/", record.original_filename)
        self.assertNotIn("..", record.original_filename.split(".")[0])


class ValidationTests(EvidenceTestCase):
    def test_disallowed_types_are_refused(self):
        self.assertEqual(self.announce(self.citizen, content_type="application/x-msdownload").status_code, 400)
        self.assertEqual(self.announce(self.citizen, content_type="text/html").status_code, 400)

    def test_size_limits_depend_on_the_kind_of_file(self):
        mb = 1024 * 1024
        self.assertEqual(self.announce(self.citizen, size_bytes=26 * mb).status_code, 400)
        self.assertEqual(self.announce(self.citizen, size_bytes=100 * mb, content_type="video/mp4", name="a.mp4").status_code, 201)
        self.assertEqual(self.announce(self.citizen, size_bytes=201 * mb, content_type="video/mp4", name="a.mp4").status_code, 400)

    def test_the_checksum_must_be_a_sha256(self):
        self.assertEqual(self.announce(self.citizen, sha256="abc").status_code, 400)

    @override_settings(EVIDENCE_MAX_FILES_PER_COMPLAINT=2)
    def test_the_number_of_files_per_complaint_is_capped(self):
        self.announce(self.citizen)
        self.announce(self.citizen)
        self.assertEqual(self.announce(self.citizen).status_code, 400)

    def test_the_upload_must_be_exactly_the_declared_size(self):
        file_id = self.announce(self.citizen).json()["file_id"]
        self.assertEqual(self.send(self.citizen, file_id, PHOTO + b"extra").status_code, 400)
        self.assertEqual(self.send(self.citizen, file_id, PHOTO[:-1]).status_code, 400)

    def test_a_file_that_does_not_match_its_checksum_is_discarded(self):
        content = b"\xff\xd8\xff" + b"A" * 100
        file_id = self.announce(self.citizen, content=content).json()["file_id"]
        self.send(self.citizen, file_id, b"\xff\xd8\xff" + b"B" * 100)  # same size, different bytes

        response = self.complete(self.citizen, file_id)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(EvidenceFile.objects.filter(pk=file_id).exists())
        self.assertFalse(any(Path(self.storage_dir.name).rglob(file_id)))

    def test_completing_before_uploading_is_a_conflict(self):
        file_id = self.announce(self.citizen).json()["file_id"]
        self.assertEqual(self.complete(self.citizen, file_id).status_code, 409)

    def test_only_the_uploader_can_send_or_complete(self):
        file_id = self.announce(self.citizen).json()["file_id"]
        self.assertEqual(self.send(self.si, file_id).status_code, 404)
        self.assertEqual(self.complete(self.si, file_id).status_code, 404)

    def test_completing_twice_is_harmless(self):
        file_id = self.upload_fully(self.citizen)
        again = self.complete(self.citizen, file_id)
        self.assertEqual(again.status_code, 200)
        self.assertTrue(again.json()["uploaded"])


class DownloadRulesTests(EvidenceTestCase):
    def test_a_file_that_has_not_been_scanned_is_not_released(self):
        file_id = self.upload_fully(self.citizen, scanner=UnconfiguredScanner)
        self.assertEqual(self.download(self.citizen, file_id).status_code, 409)

    @override_settings(EVIDENCE_ALLOW_UNSCANNED=True)
    def test_unscanned_files_can_be_allowed_for_development(self):
        file_id = self.upload_fully(self.citizen, scanner=UnconfiguredScanner)
        self.assertEqual(self.download(self.citizen, file_id).status_code, 200)

    @override_settings(EVIDENCE_ALLOW_UNSCANNED=True)
    def test_an_infected_file_is_never_released(self):
        file_id = self.upload_fully(self.citizen, scanner=InfectedScanner)
        self.assertEqual(self.download(self.citizen, file_id).status_code, 403)

    def test_a_file_still_uploading_cannot_be_downloaded(self):
        file_id = self.announce(self.citizen).json()["file_id"]
        self.assertEqual(self.download(self.citizen, file_id).status_code, 409)

    def test_only_people_who_can_see_the_complaint_can_download(self):
        file_id = self.upload_fully(self.citizen)
        self.assertEqual(self.download(self.si, file_id).status_code, 200)
        self.assertEqual(self.download(self.other_citizen, file_id).status_code, 404)
        self.assertEqual(self.download(self.si_b, file_id).status_code, 404)
        self.assertEqual(self.download(self.admin, file_id).status_code, 403)

    def test_downloads_are_audited(self):
        file_id = self.upload_fully(self.citizen)
        self.download(self.si, file_id)
        self.assertEqual(AuditLog.objects.get(action="evidence_download").actor, self.si)

    def test_a_scan_that_crashes_leaves_the_file_unreleased(self):
        file_id = self.announce(self.citizen).json()["file_id"]
        self.send(self.citizen, file_id)
        with patch("users.evidence_api.get_scanner", side_effect=RuntimeError("scanner exploded")):
            done = self.complete(self.citizen, file_id).json()
        self.assertEqual(done["scan_status"], "failed")
        self.assertEqual(self.download(self.citizen, file_id).status_code, 409)


class StorageTests(SimpleTestCase):
    def test_local_storage_refuses_keys_that_escape_its_folder(self):
        with tempfile.TemporaryDirectory() as root, override_settings(EVIDENCE_ROOT=root):
            with self.assertRaises(ValueError):
                LocalFileStorage().save("../outside", [b"x"])

    def test_a_failed_save_leaves_no_partial_file(self):
        def broken():
            yield b"partial"
            raise OSError("disk full")

        with tempfile.TemporaryDirectory() as root, override_settings(EVIDENCE_ROOT=root):
            with self.assertRaises(OSError):
                LocalFileStorage().save("evidence/a/b", broken())
            self.assertEqual(list(Path(root).rglob("*")) and [p for p in Path(root).rglob("*") if p.is_file()], [])

    @override_settings(EVIDENCE_S3_BUCKET="evidence-bucket", EVIDENCE_S3_REGION="ap-south-1", EVIDENCE_S3_ENDPOINT_URL="")
    def test_s3_gives_signed_urls_so_files_skip_the_api(self):
        with patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test"}):
            storage = S3Storage()
            upload = storage.presigned_upload("evidence/c/f", "image/jpeg", 1234)
            download = storage.presigned_download("evidence/c/f", 'we"ird.jpg', "image/jpeg")

        self.assertEqual(upload["method"], "PUT")
        self.assertIn("evidence-bucket", upload["url"])
        self.assertIn("X-Amz-Signature", upload["url"])
        self.assertEqual(upload["headers"], {"Content-Type": "image/jpeg"})
        self.assertIn("X-Amz-Signature", download)
        self.assertNotIn('we"ird', download)


class ClamdScannerTests(SimpleTestCase):
    def serve(self, reply):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        received = {}

        def run():
            connection, _ = server.accept()
            data = b""
            while not data.endswith(b"\x00\x00\x00\x00"):
                part = connection.recv(65536)
                if not part:
                    break
                data += part
            received["data"] = data
            connection.sendall(reply)
            connection.close()
            server.close()

        threading.Thread(target=run, daemon=True).start()
        return server.getsockname()[1], received

    def scan(self, port):
        return ClamdScanner("127.0.0.1", port, timeout=5).scan(lambda: BytesIO(b"file contents"))

    def test_clean_files_pass(self):
        port, received = self.serve(b"stream: OK\0")
        self.assertEqual(self.scan(port), "clean")
        self.assertTrue(received["data"].startswith(b"zINSTREAM\0"))
        self.assertIn(b"file contents", received["data"])

    def test_infected_files_are_flagged(self):
        port, _ = self.serve(b"stream: Eicar-Test-Signature FOUND\0")
        self.assertEqual(self.scan(port), "infected")

    def test_an_unreachable_scanner_is_a_failure_not_a_pass(self):
        free = socket.socket()
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
        free.close()
        self.assertEqual(self.scan(port), "failed")

    def test_an_unexpected_reply_is_a_failure(self):
        port, _ = self.serve(b"stream: size limit exceeded ERROR\0")
        self.assertEqual(self.scan(port), "failed")
