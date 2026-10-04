from __future__ import annotations

import unittest

from evaluation.scorer.edits import Edit, EditError, VerificationError, apply_edits, check_edits, verify


class EditTests(unittest.TestCase):
    def test_apply_single_and_adjacent_edits(self) -> None:
        self.assertEqual(apply_edits("DB_PASSWORD=mysecret123\n", [Edit(12, 23, "[P_1]")]), "DB_PASSWORD=[P_1]\n")
        self.assertEqual(apply_edits("abcdef", [Edit(1, 3, "X"), Edit(3, 5, "Y")]), "aXYf")

    def test_unsorted_input_is_sorted(self) -> None:
        edits = [Edit(4, 5, "B"), Edit(0, 1, "A")]
        self.assertEqual(check_edits("abcdef", edits), [Edit(0, 1, "A"), Edit(4, 5, "B")])
        self.assertEqual(apply_edits("abcdef", edits), "AbcdBf")

    def test_invalid_edits_raise_edit_error(self) -> None:
        cases = {
            "outside": [Edit(2, 7, "X")],
            "empty": [Edit(2, 2, "X")],
            "reversed": [Edit(3, 2, "X")],
            "negative": [Edit(-1, 2, "X")],
            "overlap": [Edit(0, 3, "X"), Edit(2, 4, "Y")],
            "non_integer": [Edit(True, 2, "X")],  # type: ignore[arg-type]
        }
        for name, edits in cases.items():
            with self.subTest(name), self.assertRaises(EditError):
                check_edits("abcdef", edits)

    def test_verify_accepts_matching_output(self) -> None:
        self.assertEqual(verify("key=abc", "key=[K]", [Edit(4, 7, "[K]")]), [Edit(4, 7, "[K]")])

    def test_verify_rejects_output_with_exposed_tail_without_leaking_text(self) -> None:
        original = "API_TOKEN=qpwoeirutyalskdjfhg\n"
        claimed = [Edit(10, 29, "[TOKEN_1]")]
        actual_output = "API_TOKEN=[TOKEN_1]skdjfhg\n"
        with self.assertRaises(VerificationError) as caught:
            verify(original, actual_output, claimed)
        message = str(caught.exception)
        self.assertIn("offset 19", message)
        for fragment in ("qpwoeirutyalskdjfhg", "skdjfhg", "TOKEN", "API_TOKEN"):
            self.assertNotIn(fragment, message)


if __name__ == "__main__":
    unittest.main()
