from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from matte_review import review


class MatteReviewTest(unittest.TestCase):
    def test_all_cutout_groups_are_reviewed_across_sheets(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            source=root/"card.png"; Image.new("RGB",(40,50),"white").save(source)
            cutout=root/"piece.png"; Image.new("RGBA",(1,1),"black").save(cutout)
            layers=[{"name":f"piece-{index}","role":"prop","path":cutout,
                     "box":[0,0,1,1],"z_index":index,"moving":True} for index in range(25)]
            card=SimpleNamespace(layers=layers,provenance="producer",reconstruction={"max_error":0})
            deck=SimpleNamespace(pages=[SimpleNamespace(path=source,source_card=card)])
            result=review(deck,root/"review")["cards"][0]
            self.assertEqual(result["shown_groups"],25)
            self.assertEqual(result["omitted_groups"],[])
            self.assertEqual([len(sheet["groups"]) for sheet in result["cutout_sheets"]],[24,1])
            self.assertTrue(all(Path(sheet["file"]).is_file() for sheet in result["cutout_sheets"]))


if __name__=="__main__": unittest.main()
