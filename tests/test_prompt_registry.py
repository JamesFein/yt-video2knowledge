from __future__ import annotations

import hashlib
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROMPT_ROOT = ROOT / "prompts"
EXPERIMENT_PROMPT_ROOT = PROMPT_ROOT / "experiments" / "summary-prompt-v1"

HISTORICAL_PROMPT_HASHES = {
    "categories/argument-v1.md": "c4cdb09dd290dc2af9116d1c0df3835ce84928a633d8e94cbc4989f855f97a81",
    "categories/briefing-v1.md": "575a1aec4feb5728c729a6c7b029da361a16d5b36fc9d5136f0b389b905df548",
    "categories/narrative-v1.md": "6b1409f796d8aa3f8ab5a204cde2efe86d705a8aaa36997cd8f860f4bb24af96",
    "categories/tutorial-v1.md": "c467a984339db4fefa556d192bf1247b8ccb6efad2a9c10ddf74dbd30c568f6a",
    "classifier.md": "8cee8a3d651d6233e2f9e61061838e5fb04f7f93f7b8d9970eed00f778c2adb9",
    "current-production.md": "4df6e8ad265b4f7c679953d6f7324f79648b2ed9c3342c41187fe06c25057145",
    "final-candidate.md": "dd6d056cf3bc0750bc29ff08b5ff20b8a55ff6b16eacccc9c9301fb817467d95",
    "general-v1.md": "50d44c2929dedbef25e52d94402384d64d782d3344b67b316444b0230c63ad90",
    "general-v2.md": "24fa9fa043c56753a43f5fe46f25b33fbc072bd2b54a5de66738a98ea903853a",
    "general-v3.md": "dd6d056cf3bc0750bc29ff08b5ff20b8a55ff6b16eacccc9c9301fb817467d95",
    "general-v4.md": "40e470d4f2d5bc9fa26d67b16be46501a9dfcc9f3147a31eec71c287512dc46b",
    "general-v5.md": "c1bb4f3a7a3bf02ce6f0ea30594049d52ebe4cfc45004666174c98a786260370",
    "judge-pair.md": "4b5e2f894fe17dba457c86694775b93248048397603e65e31753881f29fe80a7",
}


def _load_experiment_module():
    path = ROOT / "experiments" / "summary-prompt-v1" / "run_experiment.py"
    spec = importlib.util.spec_from_file_location("summary_prompt_experiment", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PromptRegistryTests(unittest.TestCase):
    def test_registry_contains_all_seventeen_nonempty_prompts(self) -> None:
        prompt_paths = sorted((PROMPT_ROOT / "production").glob("*.md"))
        prompt_paths.extend(sorted(EXPERIMENT_PROMPT_ROOT.rglob("*.md")))

        self.assertEqual(len(prompt_paths), 17)
        for path in prompt_paths:
            with self.subTest(path=path):
                self.assertTrue(path.read_text(encoding="utf-8").strip())

    def test_production_completion_markers_are_in_prompt_files(self) -> None:
        article = (PROMPT_ROOT / "production" / "summary-article-v5.md").read_text(encoding="utf-8")
        evidence = (PROMPT_ROOT / "production" / "summary-evidence-v1.md").read_text(encoding="utf-8")

        self.assertIn("<!-- SUMMARY_COMPLETE -->", article)
        self.assertIn("<!-- EVIDENCE_COMPLETE -->", evidence)

    def test_historical_experiment_prompt_hashes_are_unchanged(self) -> None:
        for relative_path, expected_hash in HISTORICAL_PROMPT_HASHES.items():
            with self.subTest(path=relative_path):
                payload = (EXPERIMENT_PROMPT_ROOT / relative_path).read_bytes()
                self.assertEqual(hashlib.sha256(payload).hexdigest(), expected_hash)

    def test_experiment_variants_load_from_central_registry(self) -> None:
        module = _load_experiment_module()

        self.assertEqual(module.PROMPT_DIR, EXPERIMENT_PROMPT_ROOT)
        expected_variants = {
            "current": "current-production.md",
            "general": "general-v1.md",
            "general_v2": "general-v2.md",
            "general_v3": "general-v3.md",
            "general_v4": "general-v4.md",
            "gpt_general_v5": "general-v5.md",
        }
        for variant, filename in expected_variants.items():
            with self.subTest(variant=variant):
                expected = (EXPERIMENT_PROMPT_ROOT / filename).read_text(encoding="utf-8").strip()
                self.assertEqual(module._generation_system(variant, "argument"), expected)

        category_prompt = module._generation_system("category", "argument")
        self.assertIn(module._read_prompt("general-v1.md").strip(), category_prompt)
        self.assertIn(module._read_prompt("categories/argument-v1.md").strip(), category_prompt)
        self.assertTrue(module._read_prompt("classifier.md"))
        self.assertTrue(module._read_prompt("judge-pair.md"))
        self.assertEqual(
            module._read_prompt("judge-stability.md").strip(),
            "比较同一 transcript 在同一提示词下生成的两篇文章。只依据 transcript 判断两篇是否忠实，"
            "以及它们是否选择了实质相同的核心认识。只输出 JSON："
            '{"run_a_faithful":true,"run_b_faithful":true,"same_core_insight":true,"reason":"..."}',
        )

    def test_model_entrypoints_do_not_embed_stable_system_prompts(self) -> None:
        production_source = (ROOT / "scripts" / "knowledge_digest.py").read_text(encoding="utf-8")
        experiment_source = (
            ROOT / "experiments" / "summary-prompt-v1" / "run_experiment.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("你是一个中文知识编辑，请把多条视频摘要整理成每日总览", production_source)
        self.assertNotIn("你是匿名文章评审。你会看到同一篇 transcript", experiment_source)
        self.assertNotIn("比较同一 transcript 在同一提示词下生成的两篇文章", experiment_source)
        self.assertIn('_read_prompt("classifier.md")', experiment_source)
        self.assertIn('_read_prompt("judge-pair.md")', experiment_source)
        self.assertIn('_read_prompt("judge-stability.md")', experiment_source)


if __name__ == "__main__":
    unittest.main()
