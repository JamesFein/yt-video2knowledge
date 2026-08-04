from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from yt_video2knowledge import cli


class DigestCliTests(unittest.TestCase):
    def run_digest(self, *args: str, manifest: dict | None = None) -> tuple[int, mock.Mock]:
        result = manifest or {"failed_count": 0, "pending_summary_count": 0}
        with mock.patch.object(cli, "run_knowledge_digest", return_value=result) as run:
            with mock.patch.object(cli, "_sync_target_date", return_value=0):
                exit_code = cli.main(["digest", "--target-date", "2026-03-21", *args])
        return exit_code, run

    def test_digest_passes_full_reprocess_flag(self) -> None:
        exit_code, run = self.run_digest("--full-reprocess")
        self.assertEqual(exit_code, 0)
        self.assertTrue(run.call_args.kwargs["full_reprocess"])

    def test_digest_passes_regenerate_summaries_flag(self) -> None:
        exit_code, run = self.run_digest("--regenerate-summaries")
        self.assertEqual(exit_code, 0)
        self.assertTrue(run.call_args.kwargs["regenerate_summaries"])

    def test_digest_passes_single_video_and_manual_summary_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "summary.md"
            summary_path.write_text("# summary", encoding="utf-8")
            exit_code, run = self.run_digest(
                "--video-id",
                "abc123xyz89",
                "--force-summary-retry",
                "--adopt-summary-file",
                str(summary_path),
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(run.call_args.kwargs["video_id"], "abc123xyz89")
        self.assertTrue(run.call_args.kwargs["force_summary_retry"])
        self.assertEqual(run.call_args.kwargs["adopt_summary_file"], summary_path)

    def test_content_digest_syncs_target_date(self) -> None:
        with mock.patch.object(
            cli,
            "run_knowledge_digest",
            return_value={"failed_count": 0, "pending_summary_count": 0},
        ):
            with mock.patch.object(cli, "_sync_target_date", return_value=0) as sync:
                exit_code = cli.main(["digest", "--target-date", "2026-03-21"])
        self.assertEqual(exit_code, 0)
        sync.assert_called_once_with("2026-03-21", mode="auto")

    def test_sync_failure_returns_nonzero(self) -> None:
        with mock.patch.object(cli, "run_knowledge_digest", return_value={}):
            with mock.patch.object(cli, "_sync_target_date", return_value=1):
                exit_code = cli.main(["digest", "--target-date", "2026-03-21"])
        self.assertEqual(exit_code, 1)

    def test_partial_manifest_returns_partial_exit_code_after_sync(self) -> None:
        manifest = {"failed_count": 0, "pending_summary_count": 1}
        with mock.patch.object(cli, "run_knowledge_digest", return_value=manifest):
            with mock.patch.object(cli, "_sync_target_date", return_value=0):
                exit_code = cli.main(["digest", "--target-date", "2026-03-21"])
        self.assertEqual(exit_code, 2)

    def test_non_content_mode_skips_sync(self) -> None:
        with mock.patch.object(cli, "run_knowledge_digest", return_value={}):
            with mock.patch.object(cli, "_sync_target_date", return_value=0) as sync:
                exit_code = cli.main(["digest", "--bootstrap-login"])
        self.assertEqual(exit_code, 0)
        sync.assert_not_called()


class MaintenanceCliTests(unittest.TestCase):
    def test_sync_site_dispatches_to_site_module(self) -> None:
        settings = mock.Mock()
        report = mock.Mock()
        with mock.patch.object(cli, "load_settings", return_value=settings):
            with mock.patch.object(cli, "sync_knowledge_site", return_value=report) as sync:
                with mock.patch.object(cli, "format_sync_report", return_value="ok"):
                    exit_code = cli.main(["sync-site", "--target-date", "2026-03-21"])
        self.assertEqual(exit_code, 0)
        sync.assert_called_once_with(settings, runs_dir=None, target_date="2026-03-21")

    def test_sync_site_failure_returns_nonzero(self) -> None:
        with mock.patch.object(cli, "load_settings", return_value=mock.Mock()):
            with mock.patch.object(cli, "sync_knowledge_site", side_effect=RuntimeError("sync failed")):
                with mock.patch.object(cli, "format_sync_failure", return_value="sync failed"):
                    exit_code = cli.main(["sync-site", "--target-date", "2026-03-21"])
        self.assertEqual(exit_code, 1)

    def test_recover_manifest_dispatches_to_manifest_module(self) -> None:
        manifest = {"target_date": "2026-03-21"}
        with mock.patch.object(cli, "recover_run", return_value=manifest) as recover:
            exit_code = cli.main(["recover-manifest", "--target-date", "2026-03-21"])
        self.assertEqual(exit_code, 0)
        recover.assert_called_once_with("2026-03-21")

    def test_recover_manifest_failure_returns_nonzero(self) -> None:
        with mock.patch.object(cli, "recover_run", side_effect=cli.DigestError("missing artifacts")):
            exit_code = cli.main(["recover-manifest", "--target-date", "2026-03-21"])
        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
