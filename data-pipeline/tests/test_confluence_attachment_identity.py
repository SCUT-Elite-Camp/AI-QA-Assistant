import hashlib
import json

from models.document import Document
from parsers.markdown_parser import MarkdownParser


def test_markdown_attachments_do_not_replace_their_parent_page(tmp_path):
    page = {'page_id': '123', 'space_id': '9', 'version': 2}
    parser = MarkdownParser()
    parent = parser.parse_text('Parent content', source='parent.md', metadata=page)
    first = parser.parse_text('Attachment one', source='one.md', metadata={**page, 'attachment_id': 'att10'})
    second = parser.parse_text('Attachment two', source='two.md', metadata={**page, 'attachment_id': 'att11'})
    renamed = parser.parse_text('Attachment one', source='renamed.md', metadata={**page, 'attachment_id': 'att10'})
    assert len({parent.doc_id, first.doc_id, second.doc_id}) == 3
    assert renamed.doc_id == first.doc_id
    assert renamed.version_id == first.version_id
    assert parent.version_id != first.version_id


def test_native_attachment_parsers_share_the_same_id_contract(tmp_path):
    source = tmp_path / 'report.txt'
    source.write_text('source text', encoding='utf-8')
    meta = {'page_id': '123', 'space_id': '9', 'attachment_id': 'att10', 'version': 2}
    (tmp_path / 'report.txt.meta.json').write_text(json.dumps(meta), encoding='utf-8')
    native = Document.from_file_path(str(source), 'source text')
    markdown = MarkdownParser().parse_text('source text', source=str(source), metadata=meta)
    assert native.doc_id == markdown.doc_id == hashlib.md5(b'confluence:9:attachment:att10').hexdigest()
