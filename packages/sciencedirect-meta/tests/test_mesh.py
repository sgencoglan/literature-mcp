import unittest
from unittest.mock import AsyncMock, patch

import httpx
from sciencedirect_meta import mesh


class MeshTests(unittest.IsolatedAsyncioTestCase):
    async def test_rdf_lookup_returns_definition_and_real_descriptor_id(self):
        def response(data):
            return httpx.Response(
                200, json=data, request=httpx.Request("GET", "https://example.org")
            )

        replies = [
            response([{"resource": "http://id.nlm.nih.gov/mesh/D000374", "label": "Aggression"}]),
            response(
                {
                    "label": {"@value": "Aggression"},
                    "preferredConcept": "http://id.nlm.nih.gov/mesh/M0000572",
                    "treeNumber": ["http://id.nlm.nih.gov/mesh/F01.145"],
                }
            ),
            response({"scopeNote": {"@value": "Fixture scope note."}}),
            response({"terms": [{"label": "Aggression"}]}),
        ]
        with patch.object(mesh, "polite_get", new=AsyncMock(side_effect=replies)):
            result = await mesh.lookup("Aggression")
        self.assertTrue(result["found"])
        entry = result["entries"][0]
        self.assertEqual(entry["identifier"], "D000374")
        self.assertEqual(entry["scope_note"], "Fixture scope note.")
        self.assertEqual(entry["narrower_tree_numbers"], [])
        self.assertEqual(entry["tree_numbers"], ["F01.145"])

    async def test_failed_lookup_never_fabricates_entry_or_exposes_url_secrets(self):
        with patch.object(
            mesh, "polite_get", new=AsyncMock(side_effect=RuntimeError("api_key=secret"))
        ):
            result = await mesh.lookup("fixture")
        self.assertFalse(result["found"])
        self.assertEqual(result["error"], "RuntimeError")
        self.assertNotIn("secret", str(result))

    def test_pubmed_keeps_inline_title_and_structured_abstract(self):
        text = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID>
        <Article><ArticleTitle>Effect of <i>fixture</i> intervention</ArticleTitle>
        <Abstract><AbstractText Label="METHODS">A <b>small</b> sample.</AbstractText>
        <AbstractText Label="RESULTS">Mixed findings.</AbstractText></Abstract></Article>
        <MeshHeadingList><MeshHeading><DescriptorName>Fixture</DescriptorName></MeshHeading></MeshHeadingList>
        </MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1000/fixture</ArticleId>
        </ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>"""
        article = mesh._parse_pubmed_mesh(text)[0]
        self.assertEqual(article["title"], "Effect of fixture intervention")
        self.assertIn("METHODS: A small sample.", article["abstract"])
        self.assertIn("RESULTS: Mixed findings.", article["abstract"])
        self.assertEqual(article["doi"], "10.1000/fixture")


if __name__ == "__main__":
    unittest.main()
