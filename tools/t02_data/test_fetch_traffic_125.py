"""Offline sanity tests for collector. Run: python -m unittest test_fetch_traffic_125.py"""
import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import numpy as np
import fetch_traffic_125 as m

class TestCollector(unittest.TestCase):
    def test_similar_and_distinct(self):
        a = Image.fromarray(np.uint8(np.random.default_rng(0).integers(0,255,(300,500,3))))
        b = Image.fromarray(np.uint8(np.random.default_rng(1).integers(0,255,(300,500,3))))
        def row(i, d):
            return {"sha256":str(i), "dhash":m.d_hash(d),"ahash":m.a_hash(d),"width":d.width,"height":d.height}
        self.assertTrue(m.looks_duplicate(row('1',a),[row('1',a)]))
        self.assertTrue(m.looks_duplicate(row('2',a),[row('1',a)]))
        self.assertFalse(m.looks_duplicate(row('3',b),[row('1',a)]))

    def test_filename_cues(self):
        self.assertTrue(m.has_traffic_hint('Road traffic in Hanoi.jpg'))
        self.assertFalse(m.has_traffic_hint('Traffic map diagram.png'))
        self.assertFalse(m.has_traffic_hint('Sunshine on the ocean.jpg'))

    def test_resumable_no_network(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            seed = folder / 'seed.csv'
            with seed.open('w',encoding='utf-8',newline='') as f:
                w=csv.DictWriter(f,fieldnames=['category','priority','commons_file_title'])
                w.writeheader()
                for g in m.GROUPS:
                    w.writerow({'category':g,'priority':1,'commons_file_title':f'Traffic {g} example.jpg'})
            # deterministic images with different structure for each group.
            pictures = {}
            metadata = {}
            for i,g in enumerate(m.GROUPS):
                rng=np.random.default_rng(i+10)
                pix=rng.integers(0,255,(380,560,3),dtype=np.uint8)
                b=io.BytesIO();Image.fromarray(pix).save(b,format='JPEG',quality=85)
                name=f'Traffic {g} example.jpg'
                pictures[name]=b.getvalue()
                metadata[name.casefold()]={'mime':'image/jpeg','url':f'https://example.test/{g}.jpg','width':560,'height':380,
                    'extmetadata':{'LicenseShortName':{'value':'CC BY 4.0'},'LicenseUrl':{'value':'https://creativecommons.org/licenses/by/4.0/'},'Artist':{'value':'Author'}}}
            def fake_fetch(self,url,*a,**kw):
                name=url.rsplit('/',1)[-1].split('.')[0]
                return pictures[f'Traffic {name} example.jpg']
            def fake_meta(net,names,width):
                return {n.casefold():metadata[n.casefold()] for n in names if n.casefold() in metadata}
            with patch.object(m.Network,'fetch',fake_fetch),patch.object(m,'metadata_batch',fake_meta):
                # no searching needed; 1 seed per group
                self.assertEqual(m.main(['--candidates',str(seed),'--out',str(folder/'out'),'--per-group','1','--pause','0']),0)
                self.assertEqual(m.main(['--candidates',str(seed),'--out',str(folder/'out'),'--per-group','1','--pause','0']),0)
            out=folder/'out'
            rows=m.csv_read(out/'source_catalog.csv')
            self.assertEqual(len(rows),5)
            self.assertEqual(len({r['sha256'] for r in rows}),5)
            self.assertEqual(len(m.csv_read(out/'images.csv')),5)
            self.assertEqual(len(m.csv_read(out/'manifest.csv')),5)
            self.assertEqual(len(m.csv_read(out/'label_review.csv')),5)
            self.assertTrue((out/'contact_sheet.html').exists())
            for r in rows:
                self.assertEqual(r['review_status'],'UNREVIEWED')

if __name__ == '__main__':
    unittest.main()
