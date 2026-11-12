"""Privacy checks reject leaks while allowing documented placeholders."""

import unittest

from check_repo_privacy import check_file


class RepoPrivacyTests(unittest.TestCase):
    def test_home_paths_on_multiple_platforms(self):
        for value in (
            "/home/" + "private-person/work/papers",
            "/Users/" + "private-person/Documents",
            "C:\\Users\\" + "private-person\\Documents",
        ):
            with self.subTest(value=value):
                self.assertTrue(check_file("config.json", value))

    def test_placeholders_and_example_addresses_are_allowed(self):
        self.assertEqual(check_file(
            "README.md", "/home/you/papers <home>/papers research@example.org",
        ), [])

    def test_secret_values_are_not_in_findings(self):
        secret = "gh" + "p_" + "a" * 36
        findings = check_file("config.json", secret)
        self.assertTrue(findings)
        self.assertNotIn(secret, "\n".join(findings))

    def test_personal_email_is_reported(self):
        self.assertTrue(check_file("README.md", "person@" + "mail.invalid"))

    def test_local_files_are_rejected_even_without_sensitive_content(self):
        for path in (
            ".literature-mcp/projects.json", "config/opencode.local.json",
            "03_kaynak_kesfi/pool.json", "model.gguf", ".env.production",
        ):
            with self.subTest(path=path):
                self.assertTrue(check_file(path, ""))
        self.assertEqual(check_file(".env.example", ""), [])
        self.assertEqual(check_file("examples/projects.example.json", "{}"), [])
