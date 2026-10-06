from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageChops

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from auto_plan import import_images, plan_package
from flat_layers import export_flat_layers, _reading_lines, _refine_full_resolution, _couple_paint_ownership, _light_surface
from source_layers import LayerRepairRequired, load_source_card, file_sha
from native_focus import Deck
from hyperframes_renderer import create_project


def illustrated(path: Path) -> None:
    image = Image.new("RGB",(400,500),(218,187,243)); draw=ImageDraw.Draw(image)
    draw.rectangle((40,25,320,65),fill="black")
    draw.rounded_rectangle((25,105,375,190),20,fill="white",outline="black",width=4)
    draw.rectangle((60,135,300,155),fill="black")
    draw.ellipse((70,285,205,420),fill="white",outline="black",width=4)
    draw.ellipse((103,330,112,339),fill="black"); draw.ellipse((164,330,173,339),fill="black")
    draw.rounded_rectangle((75,395,202,498),15,fill="white",outline="black",width=4)
    image.save(path)


class FlatLayersTest(unittest.TestCase):
    def test_cream_and_lavender_panels_are_not_punched_out(self):
        for color in ((242,253,223),(239,229,253)):
            with self.subTest(color=color),tempfile.TemporaryDirectory() as folder:
                source=Path(folder)/"card.png"; illustrated(source)
                image=Image.open(source).convert("RGB")
                ImageDraw.Draw(image).rounded_rectangle((25,105,375,190),20,fill=color)
                ImageDraw.Draw(image).rectangle((60,135,300,155),fill="black")
                image.save(source)
                metadata=export_flat_layers(source,[],{})
                card=load_source_card(metadata,source)
                occupied=Image.new("L",card.size)
                for layer in card.layers:
                    if layer["moving"]:
                        full=Image.new("L",card.size)
                        full.paste(Image.open(layer["path"]).getchannel("A"),layer["box"][:2])
                        occupied=ImageChops.lighter(occupied,full)
                self.assertEqual(occupied.getpixel((60,170)),255)
                self.assertEqual(card.reconstruction["max_error"],0)

    def test_light_surface_does_not_select_the_lavender_background_cloud(self):
        cloud=Image.new("RGB",(1,1),(230,213,248))
        self.assertEqual(_light_surface(cloud).getpixel((0,0)),0)

    def test_split_contours_and_white_interiors_share_one_motion_group(self):
        paint=Image.new("L",(100,100)); ImageDraw.Draw(paint).ellipse((10,10,90,90),fill=255)
        left=paint.copy(); ImageDraw.Draw(left).rectangle((50,0,99,99),fill=0)
        right=ImageChops.subtract(paint,left)
        self.assertEqual(_couple_paint_ownership([left,right],paint,[1,2]),[1,1])

    def test_neighboring_but_disconnected_paint_keeps_independent_motion(self):
        left=Image.new("L",(100,100)); right=left.copy()
        ImageDraw.Draw(left).rectangle((10,10,45,90),fill=255)
        ImageDraw.Draw(right).rectangle((55,10,90,90),fill=255)
        paint=ImageChops.lighter(left,right)
        self.assertEqual(_couple_paint_ownership([left,right],paint,[1,2]),[1,2])

    def test_source_resolution_matte_removes_thumbnail_halo(self):
        coarse = Image.new("L",(400,500)); evidence = coarse.copy()
        ImageDraw.Draw(coarse).rectangle((60,60,220,230),fill=255)
        ImageDraw.Draw(evidence).ellipse((90,85,190,205),outline=255,width=4)
        refined = _refine_full_resolution(coarse,evidence)
        self.assertEqual(refined.getpixel((65,70)),0)
        self.assertEqual(refined.getpixel((140,130)),255)
        self.assertEqual(refined.getpixel((140,82)),0)

    def test_occluder_stroke_closes_a_visible_figure_interior(self):
        coarse=Image.new("L",(400,500)); evidence=coarse.copy()
        draw=ImageDraw.Draw(evidence)
        draw.arc((95,85,190,205),180,360,fill=255,width=4)
        draw.line((95,144,95,201),fill=255,width=4)
        draw.line((187,144,187,201),fill=255,width=4)
        draw.line((90,203,195,203),fill=255,width=4)
        coarse.paste(evidence.crop((90,80,196,200)),(90,80))
        refined=_refine_full_resolution(coarse,evidence)
        self.assertEqual(refined.getpixel((140,150)),255)

    def test_source_canvas_crop_keeps_the_visible_figure_interior(self):
        evidence=Image.new("L",(400,500))
        ImageDraw.Draw(evidence).ellipse((90,340,210,610),outline=255,width=4)
        refined=_refine_full_resolution(evidence.copy(),evidence)
        self.assertEqual(refined.getpixel((150,480)),255)
        self.assertEqual(refined.getpixel((150,499)),255)
        self.assertEqual(refined.getpixel((70,480)),0)

    def test_pixels_exact_and_no_face_parts_animated_independently(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/"card.png"; illustrated(source)
            before=source.read_bytes()
            metadata=export_flat_layers(source,[("title",[35,20,295,50]),("body",[55,125,260,40])],{"available":True})
            card=load_source_card(metadata,source)
            self.assertEqual(card.reconstruction["max_error"],0)
            self.assertEqual(source.read_bytes(),before)
            figures=[layer for layer in card.layers if layer["role"]=="character"]
            self.assertEqual(len(figures),1)
            self.assertGreater(figures[0]["box"][3],180)
            self.assertEqual(export_flat_layers(source,[("title",[35,20,295,50]),("body",[55,125,260,40])],{"available":True}),metadata)
            self.assertNotEqual(export_flat_layers(source,[],{}),metadata)
            background=Image.open(card.background).convert("RGB")
            self.assertIsNone(ImageChops.difference(background,background.crop((0,0,1,500)).resize((400,500))).getbbox())
            self.assertTrue(any(layer.get("reveal_after_motion") and not layer["moving"] for layer in card.layers))

    def test_changed_pixels_get_new_assets_not_old_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/"card.png"; illustrated(source)
            first=export_flat_layers(source,[],{})
            image=Image.open(source); ImageDraw.Draw(image).rectangle((230,300,320,430),fill="black"); image.save(source)
            second=export_flat_layers(source,[],{})
            self.assertNotEqual(first,second)
            with self.assertRaises(LayerRepairRequired): load_source_card(first,source)
            self.assertEqual(load_source_card(second,source).reconstruction["max_error"],0)

    def test_interrupted_metadata_publication_recovers_existing_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/"card.png"; illustrated(source)
            with patch("flat_layers.os.replace", side_effect=OSError("interrupted publication")):
                with self.assertRaises(OSError):
                    export_flat_layers(source,[],{})
            assets=list((source.parent/"extracted-layers").iterdir())
            self.assertEqual(len(assets),1)
            before={path.name:file_sha(path) for path in assets[0].iterdir()}
            metadata=export_flat_layers(source,[],{})
            self.assertEqual(load_source_card(metadata,source).reconstruction["max_error"],0)
            self.assertEqual(before,{path.name:file_sha(path) for path in assets[0].iterdir()})

    def test_invalid_group_identifiers_fail_before_planning(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/"card.png"; illustrated(source)
            metadata=export_flat_layers(source,[],{})
            original=json.loads(metadata.read_text())
            for key in ("motion_group","reading_group"):
                for value in ([],{},""," ","x"*81):
                    data=json.loads(json.dumps(original))
                    data["layers"][0][key]=value
                    metadata.write_text(json.dumps(data))
                    with self.subTest(key=key,value=value):
                        with self.assertRaisesRegex(LayerRepairRequired,key):
                            load_source_card(metadata,source)

    def test_blank_and_dark_inputs_do_not_claim_success(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/"card.png"
            for color in ("white","black"):
                Image.new("RGB",(400,500),color).save(source)
                with self.assertRaises(LayerRepairRequired): export_flat_layers(source,[],{})

    def test_png_only_import_creates_all_inputs_without_authored_boxes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); images=[]
            for index in range(4):
                image=root/f"{index}.png"; illustrated(image); images.append(image)
            with patch("auto_plan._ocr",return_value=([("original text",[35,20,295,50])],{"available":True})):
                manifest=import_images(images,root/"output","new cards")
            data=json.loads(manifest.read_text())
            self.assertEqual(data["source_kind"],"flat_images")
            self.assertTrue(all(c["layers_file"] and c["motion_elements"] for c in data["cards"]))
            self.assertEqual(len(Deck(manifest).pages),4)
            initial=manifest.read_bytes()
            plan_package(manifest)
            self.assertEqual(manifest.read_bytes(),initial)
            for original,record in zip(images,data["cards"]):
                self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(),record["source_sha256"])

    def test_ocr_words_form_lines_without_joining_distant_columns(self):
        lines=_reading_lines([("one",[20,50,40,20]),("two",[65,51,45,20]),("column",[280,50,60,20])],400)
        self.assertEqual(len(lines),2)
        self.assertEqual(lines[0][0],"one two")

    def test_dirty_entry_plate_rejected_even_if_original_residual_hides_it(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/"card.png"; illustrated(source)
            metadata=export_flat_layers(source,[],{})
            data=json.loads(metadata.read_text())
            background=metadata.parent/data["background"]["file"]
            pixels=Image.open(background).copy(); pixels.putpixel((0,0),(0,0,0,255)); pixels.save(background)
            data["background"]["sha256"]=file_sha(background)
            metadata.write_text(json.dumps(data))
            with self.assertRaisesRegex(LayerRepairRequired,"잔상"):
                load_source_card(metadata,source)

    def test_png_project_has_no_original_overlay_and_groups_parent_text_motion(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); images=[]
            for index in range(4):
                source=root/f"{index}.png"; illustrated(source); images.append(source)
            with patch("auto_plan._ocr",return_value=([("title",[35,20,295,50]),("body",[55,125,260,40])],{"available":True})):
                manifest=import_images(images,root/"output","cards")
            deck=Deck(manifest)
            project=create_project(deck,root/"project")
            generated=json.loads((project.parent/"generated.json").read_text())
            self.assertFalse(generated["original_card_overlay"])
            self.assertNotIn('id="original-01"',project.read_text())
            page=deck.pages[0]; planned={item.name:item for item in page.elements}
            groups={}
            for layer in page.source_card.layers:
                if layer["moving"]:
                    item=planned[layer["name"]]
                    groups.setdefault(layer["motion_group"],set()).add((item.delay_ms,item.effect))
            self.assertTrue(all(len(value)==1 for value in groups.values()))
            self.assertIn('class="moving-element motion-group"',project.read_text())
            self.assertIn('class="source-piece"',project.read_text())
            self.assertIn('CardMotionEffects.animate',project.read_text())

    def test_browser_resamples_each_rigid_group_as_one_original_pixel_raster(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); images=[]
            for index in range(4):
                source=root/f"{index}.png"; illustrated(source); images.append(source)
            with patch("auto_plan._ocr",return_value=([("body",[55,125,260,40])],{"available":True})):
                manifest=import_images(images,root/"output","cards")
            deck=Deck(manifest); project=create_project(deck,root/"project")
            html=project.read_text()
            self.assertEqual(html.count('class="source-piece"'),html.count('class="moving-element motion-group"'))
            page_dir=project.parent/"assets/page-01"
            doc=json.loads((page_dir/"elements.json").read_text())
            for group in page_dir.glob('rigid-group-*.png'):
                first=int(group.stem.rsplit('-',1)[1])-1
                anchor=doc['elements'][first]
                members=[item for item in doc['elements'] if item.get('motion_group',item['name'])==anchor.get('motion_group',anchor['name'])]
                left=min(item['box'][0] for item in members); top=min(item['box'][1] for item in members)
                right=max(item['box'][0]+item['box'][2] for item in members)
                bottom=max(item['box'][1]+item['box'][3] for item in members)
                expected=Image.new('RGBA',(right-left,bottom-top))
                for item in sorted(members,key=lambda item:item['z_index']):
                    expected.alpha_composite(Image.open(page_dir/item['file']).convert('RGBA'),(item['box'][0]-left,item['box'][1]-top))
                actual=Image.open(group).convert('RGBA')
                self.assertEqual(actual.tobytes(),expected.tobytes())

    def test_ocr_child_is_disjoint_and_never_repaints_its_parent(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/"card.png"; illustrated(source)
            metadata=export_flat_layers(source,[("body",[55,125,260,40])],{"available":True})
            card=load_source_card(metadata,source)
            original=Image.open(source).convert("RGB")
            occupied=Image.new("L",card.size)
            for layer in card.layers:
                if not layer["moving"]: continue
                pixels=Image.open(layer["path"]).convert("RGBA")
                mask=pixels.getchannel("A"); box=layer["box"]
                full=Image.new("L",card.size); full.paste(mask,box[:2])
                self.assertIsNone(ImageChops.multiply(occupied,full).getbbox())
                occupied=ImageChops.lighter(occupied,full)
                difference=ImageChops.difference(pixels.convert("RGB"),original.crop(
                    (box[0],box[1],box[0]+box[2],box[1]+box[3])))
                self.assertIsNone(ImageChops.multiply(difference.convert("L"),mask).getbbox())


if __name__=="__main__": unittest.main()
