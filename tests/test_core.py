import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pipeline
from clipboard import cf_html
from pubmed import parse_articles
from writer import validate, write
from wechat import WeChat

SOURCE = {"pmid": "123", "title": "Activity in Xenopus optic tectum", "abstract": "We studied visual responses in Xenopus tadpoles. The results suggest a change in neuronal activity.",
          "doi": "10.1234/example", "authors": ["Researcher A"], "journal": "Example", "date": "2026", "url": "https://pubmed.ncbi.nlm.nih.gov/123/",
          "publication_types": ["Journal Article"], "notices": [], "evidence_level": "abstract_only"}
DRAFT = {"title": "爪蟾视顶盖研究解读", "digest": "测试来源匹配。", "generated": True,
         "sections": [{"heading": heading, "text": "摘要报告了爪蟾视觉反应的研究。", "evidence_quote": "We studied visual responses in Xenopus tadpoles."} for heading in ["研究问题", "研究方法", "主要发现"]]}


class FakeWeChat:
    calls = []
    failure = False
    appid = "test-account"
    def access_token(self):
        return "test"
    def upload_cover(self, path):
        self.calls.append("cover")
        return "cover-id"
    def upload_inline(self, path):
        self.calls.append("inline")
        return "https://example.com/image.jpg"
    def add_draft(self, article):
        self.calls.append("draft")
        if self.failure:
            raise RuntimeError("timeout; outcome unknown")
        assert "https://example.com/image.jpg" in article["content"]
        return "draft-id"
    def submit(self, media_id):
        self.calls.append("submit")
        return 99
    def status(self, publish_id):
        return {"publish_status": 0, "article_detail": {"item": [{"article_url": "https://example.com/published"}]}}
    def get_draft(self, media_id):
        return {"news_item": [{"title": DRAFT["title"], "content": pipeline.render(SOURCE, DRAFT, "https://example.com/image.jpg"), "thumb_media_id": "cover-id"}]}


class Tests(unittest.TestCase):
    def test_xml_mixed_content(self):
        xml = '''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>Visual <i>activity</i> α</ArticleTitle><Journal><Title>Journal</Title><JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue></Journal><Abstract><AbstractText Label="RESULTS">Neurons <b>respond</b>.</AbstractText></Abstract><PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList></Article><CommentsCorrectionsList><CommentsCorrections RefType="RetractionIn"><PMID>456</PMID></CommentsCorrections></CommentsCorrectionsList></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.test/α</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'''
        record = parse_articles(xml.encode("utf-8"))[0]
        self.assertEqual(record["title"], "Visual activity α")
        self.assertEqual(record["abstract"], "RESULTS: Neurons respond.")
        self.assertEqual(record["notices"][0]["type"], "RetractionIn")

    def test_invented_quote_rejected(self):
        bad = json.loads(json.dumps(DRAFT))
        bad["sections"][0]["evidence_quote"] = "This invented result is absent from the original abstract."
        with self.assertRaises(ValueError):
            validate(bad, SOURCE)
        validate(DRAFT, SOURCE)

    def test_no_key_not_a_generated_article(self):
        with patch.dict(os.environ, {"LLM_API_KEY": ""}):
            self.assertFalse(write(SOURCE, "视顶盖")["generated"])

    def test_retraction_stops_generation(self):
        with self.assertRaises(ValueError):
            write({**SOURCE, "notices": [{"type": "RetractionIn"}]}, "视顶盖")

    def test_cf_html_utf8_offsets(self):
        fragment = "<p>视顶盖 α</p>"
        payload = cf_html(fragment)
        header = payload.split(b"<html>")[0].decode("ascii")
        fields = dict(line.split(":", 1) for line in header.strip().splitlines())
        self.assertEqual(payload[int(fields["StartFragment"]):int(fields["EndFragment"])].decode("utf-8"), fragment)

    def test_render_escapes_html_and_separates_audit(self):
        draft = json.loads(json.dumps(DRAFT))
        draft["sections"][0]["text"] = '<script>alert("bad")</script>'
        normal = pipeline.render(SOURCE, draft)
        self.assertNotIn("<script>", normal)
        self.assertNotIn("来源证据", normal)
        self.assertIn("来源证据", pipeline.render(SOURCE, draft, audit=True))

    def with_bundle(self, directory):
        directory = Path(directory)
        folder = directory / "bundle"
        folder.mkdir()
        pipeline.save_json(folder / "source.json", SOURCE)
        pipeline.save_json(folder / "article.json", DRAFT)
        for name in ["cover.jpg", "source-card.jpg"]:
            (folder / name).write_bytes(b"test-image")
        return folder

    def test_publication_deduplicates_and_checks_status(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(pipeline, "DATA", Path(directory) / "state"), patch.object(pipeline, "WeChat", FakeWeChat), patch.dict(os.environ, {"WECHAT_APP_ID": "test-account"}):
            FakeWeChat.calls, FakeWeChat.failure = [], False
            folder = self.with_bundle(directory)
            self.assertEqual(pipeline.send(folder, True)["stage"], "submitted")
            self.assertEqual(pipeline.send(folder, True)["stage"], "submitted")
            self.assertEqual(FakeWeChat.calls, ["cover", "inline", "draft", "submit"])
            self.assertEqual(pipeline.status(folder)["publish_status"], 0)
            self.assertEqual(pipeline.job(folder)["stage"], "published")
            (folder / "cover.jpg").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                pipeline.send(folder, True)

    def test_unknown_outcome_does_not_retry(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(pipeline, "DATA", Path(directory) / "state"), patch.object(pipeline, "WeChat", FakeWeChat), patch.dict(os.environ, {"WECHAT_APP_ID": "test-account"}):
            FakeWeChat.calls, FakeWeChat.failure = [], True
            folder = self.with_bundle(directory)
            with self.assertRaises(RuntimeError):
                pipeline.send(folder)
            with self.assertRaises(RuntimeError):
                pipeline.send(folder)
            self.assertEqual(FakeWeChat.calls.count("draft"), 1)
            self.assertEqual(pipeline.recover(folder, media_id="verified-draft-id")["stage"], "draft")
            FakeWeChat.failure = False

    def test_wechat_error_redacts_secrets(self):
        class Response:
            status_code = 200
            def json(self):
                return {"errcode": 40164, "errmsg": "sensitive-details-token"}
        with patch.dict(os.environ, {"WECHAT_APP_ID": "a", "WECHAT_APP_SECRET": "secret"}):
            with self.assertRaises(RuntimeError) as error:
                WeChat()._decode(Response())
        self.assertNotIn("sensitive", str(error.exception))

    def test_wechat_utf8_json_with_latin1_header(self):
        import requests
        response = requests.Response()
        response.status_code = 200
        response.encoding = "ISO-8859-1"
        response._content = json.dumps({"news_item": [{"title": "爪蟾视顶盖"}]}, ensure_ascii=False).encode("utf-8")
        with patch.dict(os.environ, {"WECHAT_APP_ID": "a", "WECHAT_APP_SECRET": "secret"}):
            self.assertEqual(WeChat()._decode(response)["news_item"][0]["title"], "爪蟾视顶盖")

    def test_draft_readback_and_no_duplicate(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(pipeline, "DATA", Path(directory) / "state"), patch.object(pipeline, "WeChat", FakeWeChat), patch.dict(os.environ, {"WECHAT_APP_ID": "test-account"}):
            FakeWeChat.calls, FakeWeChat.failure = [], False
            folder = self.with_bundle(directory)
            state = pipeline.send(folder)
            self.assertEqual(state["stage"], "draft")
            self.assertTrue(json.loads(state["result"])["verified"])
            pipeline.send(folder)
            self.assertEqual(FakeWeChat.calls.count("draft"), 1)

    def test_updates_existing_draft_with_multiple_images(self):
        class UpdatingWeChat(FakeWeChat):
            stored = {}
            def add_draft(self, article):
                self.calls.append("draft")
                self.stored.update(article)
                return "draft-id"
            def upload_inline(self, path):
                self.calls.append("inline")
                return "https://example.com/" + path.stem + "/0"
            def update_draft(self, media_id, article):
                self.calls.append("update")
                assert media_id == "draft-id"
                self.stored.update(article)
            def get_draft(self, media_id):
                return {"news_item": [dict(self.stored)]}
        with tempfile.TemporaryDirectory() as directory, patch.object(pipeline, "DATA", Path(directory) / "state"), patch.object(pipeline, "WeChat", UpdatingWeChat), patch.dict(os.environ, {"WECHAT_APP_ID": "test-account"}):
            UpdatingWeChat.calls = []
            folder = self.with_bundle(directory)
            first = pipeline.send(folder)
            upgraded = json.loads(json.dumps(DRAFT))
            upgraded["sections"][0]["text"] += "增加专业解释。"
            upgraded["illustrations"] = [{"id": "schematic", "file": "schematic.jpg", "kind": "schematic"}, {"id": "fig1", "file": "paper-fig1.jpg", "kind": "paper"}]
            for fig in upgraded["illustrations"]:
                (folder / fig["file"]).write_bytes(b"new-image")
            pipeline.save_json(folder / "article.json", upgraded)
            second = pipeline.send(folder, replace_existing=True)
            self.assertEqual(first["media_id"], second["media_id"])
            self.assertEqual(json.loads(second["result"])["body_image_count"], 2)
            pipeline.send(folder, replace_existing=True)
            self.assertEqual(UpdatingWeChat.calls.count("draft"), 1)
            self.assertEqual(UpdatingWeChat.calls.count("update"), 1)

    def test_fulltext_figure_permissions_preserved(self):
        from research import parse_fulltext
        parsed = parse_fulltext('''<article><front><article-meta><permissions><license>CC BY</license></permissions></article-meta></front><body><sec><title>Results</title><p>True experiment result.</p><fig id="fig1"><label>1</label><caption><p>Complete panel caption.</p></caption><graphic xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="figure.jpg"/><permissions><copyright-statement>Third-party image</copyright-statement></permissions></fig></sec></body></article>''')
        self.assertIn("True experiment result.", parsed["fulltext"])
        self.assertEqual(parsed["paper_figures"][0]["filename"], "figure.jpg")
        self.assertEqual(parsed["paper_figures"][0]["credit"], "Third-party image")

    def test_wechat_resized_data_src_readback(self):
        class RewrittenWeChat(FakeWeChat):
            def add_draft(self, article):
                return "draft-id"
            def upload_inline(self, path):
                return "http://mmbiz.qpic.cn/image/identity/0?from=appmsg"
            def get_draft(self, media_id):
                return {"news_item": [{"title": DRAFT["title"], "content": pipeline.render(SOURCE, DRAFT, "https://mmbiz.qpic.cn/image/identity/640?from=appmsg").replace('src=', 'data-src='), "thumb_media_id": "cover-id"}]}
        with tempfile.TemporaryDirectory() as directory, patch.object(pipeline, "DATA", Path(directory) / "state"), patch.object(pipeline, "WeChat", RewrittenWeChat), patch.dict(os.environ, {"WECHAT_APP_ID": "test-account"}):
            FakeWeChat.failure = False
            state = pipeline.send(self.with_bundle(directory))
            self.assertTrue(json.loads(state["result"])["has_body_image"])


if __name__ == "__main__":
    unittest.main()
