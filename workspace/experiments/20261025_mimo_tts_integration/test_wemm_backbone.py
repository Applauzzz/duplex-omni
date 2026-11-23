import unittest
from unittest.mock import patch

from backbone import WEMM_MODEL_PATH, create_backbone
from test_backbone import Tokenizer


class WeMMBackboneTests(unittest.TestCase):
    def test_wemm_selection(self):
        with patch("transformers.AutoTokenizer.from_pretrained", return_value=Tokenizer()) as load:
            semantic, chat = create_backbone(None, "http://wemm", backbone="wemm")
        load.assert_called_once_with(WEMM_MODEL_PATH, local_files_only=True)
        self.assertEqual(semantic.code_token_ids, {"有": 10, "无": 11, "已": 12, "未": 13})
        self.assertEqual(chat.model, "wemm")
        self.assertIs(chat.enable_thinking, False)

    def test_override(self):
        with patch("transformers.AutoTokenizer.from_pretrained", return_value=Tokenizer()) as load:
            semantic, chat = create_backbone(
                None, "http://wemm", backbone="wemm", model="custom",
                tokenizer_path="/local/tokenizer")
        load.assert_called_once_with("/local/tokenizer", local_files_only=True)
        self.assertEqual(semantic.model, "custom")
        self.assertEqual(chat.model, "custom")

    def test_reject_multitoken_classifier(self):
        with patch("transformers.AutoTokenizer.from_pretrained", return_value=Tokenizer()):
            with patch.object(Tokenizer, "encode", return_value=[1, 2]):
                with self.assertRaises(ValueError):
                    create_backbone(None, "http://wemm", backbone="wemm")


if __name__ == "__main__":
    unittest.main()
