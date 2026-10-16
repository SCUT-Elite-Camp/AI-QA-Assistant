from types import SimpleNamespace
import pymupdf
from parsers.table_backends import PyMuPDFTableBackend, _split_aligned_numeric_rows, artifact_from_rows, _restore_spanned_headers
from models.document import BoundingBox

def test_borderless_numeric_table_preserves_column_roles(tmp_path):
    path=tmp_path/'aligned.pdf';doc=pymupdf.open();page=doc.new_page()
    for y,values in zip([200,220,240],[['Dataset','Train','Eval'],['Count','720k','321'],['Length','12.0','14.5']]):
        for x,value in zip([80,250,360],values):page.insert_text((x,y),value,fontsize=11)
    doc.save(path);doc.close()
    with pymupdf.open(path) as document:
        tables=PyMuPDFTableBackend().extract(document[0],1)
    assert len(tables)==1
    assert tables[0].legacy_headers()==['Dataset','Train','Eval']
    assert tables[0].body_rows()==[['Count','720k','321'],['Length','12.0','14.5']]

def test_aligned_metrics_split_rows_and_restore_only_geometric_parent_headers():
    rows=[['Metric','A','Group',None],[None,None,'Left','Right'],['Top\nMean','11\n12','21\n22','31\n32']]
    expanded=_split_aligned_numeric_rows(rows)
    assert expanded[-2:]==[['Top','11','21','31'],['Mean','12','22','32']]
    artifact=artifact_from_rows(expanded,table_id='grid',parser_name='native',page_number=1,bbox=BoundingBox(x0=0,y0=0,x1=40,y1=40),confidence=.9)
    table=SimpleNamespace(rows=[SimpleNamespace(cells=[(0,0,10,20),(10,0,20,20),(20,0,40,10),None]),SimpleNamespace(cells=[None,None,(20,10,30,20),(30,10,40,20)])])
    _restore_spanned_headers(artifact,table)
    assert artifact.header_row_count==2
    assert artifact.legacy_headers()==['Metric','A','Group / Left','Group / Right']

def test_multiline_prose_is_not_split_as_independent_metric_rows():
    rows=[['Notes','Meaning'],['two\nparagraphs','descriptive\ntext']]
    assert _split_aligned_numeric_rows(rows)==rows
