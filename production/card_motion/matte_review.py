"""Inspect actual cutouts on a neutral checkerboard, never a final-card overlay."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from native_focus import Deck


def _cutout_sheet(selected: list) -> Image.Image:
    cell_w,cell_h,columns = 300,340,4
    sheet = Image.new("RGB",(cell_w*columns,cell_h*max(1,(len(selected)+columns-1)//columns)),"#fafafa")
    draw=ImageDraw.Draw(sheet)
    for index,(name,members) in enumerate(selected):
        left=min(item["box"][0] for item in members); top=min(item["box"][1] for item in members)
        right=max(item["box"][0]+item["box"][2] for item in members)
        bottom=max(item["box"][1]+item["box"][3] for item in members)
        cutout=Image.new("RGBA",(right-left,bottom-top))
        for member in sorted(members,key=lambda item:item["z_index"]):
            cutout.alpha_composite(Image.open(member["path"]).convert("RGBA"),
                                   (member["box"][0]-left,member["box"][1]-top))
        cutout.thumbnail((cell_w-24,cell_h-54),Image.Resampling.LANCZOS)
        ox=(index%columns)*cell_w; oy=(index//columns)*cell_h
        for y in range(oy+30,oy+cell_h-10,16):
            for x in range(ox+8,ox+cell_w-8,16):
                color="#b8c4cd" if ((x-ox)//16+(y-oy)//16)%2 else "#eef1f3"
                draw.rectangle((x,y,min(x+15,ox+cell_w-9),min(y+15,oy+cell_h-11)),fill=color)
        at=(ox+(cell_w-cutout.width)//2,oy+38+(cell_h-54-cutout.height)//2)
        sheet.paste(cutout,at,cutout)
        draw.text((ox+10,oy+9),f"{name} / {members[0]['role']}",fill="#19222a")
    return sheet


def review(deck: Deck, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    pages = []
    for number, page in enumerate(deck.pages, 1):
        card = page.source_card
        if card is None:
            continue
        original = Image.open(page.path).convert("RGB")
        groups = {}
        error = 0
        for layer in card.layers:
            if not layer["moving"]:
                continue
            pixels = Image.open(layer["path"]).convert("RGBA")
            x,y,w,h = layer["box"]
            if card.provenance == "flat-pixels-3":
                difference = ImageChops.difference(pixels.convert("RGB"),original.crop((x,y,x+w,y+h)))
                maximum = ImageChops.lighter(ImageChops.lighter(*difference.split()[:2]),difference.split()[2])
                maximum = ImageChops.multiply(maximum,pixels.getchannel("A"))
                error = max(error,maximum.getextrema()[1])
            groups.setdefault(layer.get("motion_group",layer["name"]),[]).append(layer)
        if error:
            raise ValueError(f"{number}장 누끼의 불투명 픽셀이 원본 그림과 다릅니다")
        selected = sorted(groups.items(),key=lambda entry:
                          max(item["box"][2]*item["box"][3] for item in entry[1]),reverse=True)
        sheets=[]
        for offset in range(0,len(selected),24):
            suffix="" if offset == 0 else f"-{offset//24+1:02d}"
            path=output/f"card-{number:02d}-cutouts{suffix}.png"
            chunk=selected[offset:offset+24]
            _cutout_sheet(chunk).save(path)
            sheets.append({"file":str(path),"groups":[name for name,_ in chunk]})
        pages.append({"card":number,"rigid_groups":len(groups),"moving_layers":sum(map(len,groups.values())),
                      "provenance":card.provenance,"original_pixel_error":error,
                      "reconstruction":card.reconstruction,"cutouts":sheets[0]["file"] if sheets else None,
                      "cutout_sheets":sheets,"shown_groups":len(selected),"omitted_groups":[]})
    report={"cards":pages,"note":"Checkerboards expose matte fringes; exact reconstruction does not prove semantic segmentation"}
    (output/"cutout-review.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description="실제 투명 누끼와 원본 픽셀을 검수합니다")
    parser.add_argument("--manifest",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=review(Deck(args.manifest),args.output)
    print(json.dumps({"cards":len(result["cards"]),"output":str(args.output)},ensure_ascii=False))
