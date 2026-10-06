# 코드 카드뉴스·릴스 렌더러

Threads 문안 JSON을 4:5 카드 PNG와 9:16 릴스 MP4로 만든다. 새 자동 릴스는 카드 문안에서 편집 가능한 Tesseract `.tsrct`의 글자·도형·효과음 레이어를 생성한다. 기존 HTML/CSS 릴스와 수동 검수 모션은 별도 선택지로 남겨 둔다. 게시 기능은 없다.

## 디자인

- 카드 테마: `paper`, `mono`, `kraft`, `gray`, `mint`
- 만화형 카드: `comic_lavender`(밝은 라벤더 배경·검정 외곽선·원본 캐릭터·편집 가능한 글자, 1080×1350)
- 표지: `cover`, `cover_vs`, `cover_band`
- 본문: `compare`, `split`, `steps`, `flow`, `grid`, `ranked`, `keyword`, `memo`, `prompt`
- 마무리: `list`, `cta`
- 새 자동 릴스: `motion`(카드 문안에서 네이티브 모션 원본을 생성)
- 기존 수동 선택 릴스: `band`, `list`, `bold`(HTML/CSS와 FFmpeg)
- 이전 원글 전용 모션: `motion_resolution`(수작업 프로젝트를 다시 출력하는 호환 경로)

한 덱은 테마 하나만 쓴다. 문안의 `{단어}`는 강조색, `[단어]`는 마커 밑줄이다. 사람형 또는 뿔 달린 뱀 캐릭터는 보조 요소로만 쓴다.

## 직접 실행

직접 실행은 Python 3.12 이상이 필요하다. 이 Mac에서는 `/opt/homebrew/bin/python3`를 사용한다. 최상위 `run_daily.py`는 구형 시스템 Python으로 실행해도 해당 버전으로 자동 전환한다.

```bash
cd "/Users/kimmac/Documents/Project/돈 자동화/바이브코딩 릴스/production/card_render"

# 4:5 카드 4~6장
python3 render_cards.py samples/gallery/vllo/spec.json

# 기존 카드 스펙을 만화형 4:5 PNG + 편집 가능한 .tsrct로 제작
/opt/homebrew/bin/python3 render_comic_cards.py --spec path/to/spec.json --output path/to/new-comic-cards

# 9:16 릴스, 명시한 음원을 포함
python3 render_reel.py samples/gallery/vllo/spec.json --style band \
  --audio path/to/approved-audio.wav \
  --output samples/reels/vllo-band.mp4

# MP4 없이 장면별 정지 화면만 빠르게 확인
python3 render_reel.py samples/gallery/vllo/spec.json --style band --stills

# queue의 카드 준비 스펙을 릴스로 렌더
python3 build_ready.py
```

릴스는 1080×1920, 30fps다. 자동 모션은 카드 수에 따라 18.2~28.2초이고 음악 없이 전환에만 짧은 합성 효과음을 넣는다. `render_reel.py` 직접 실행은 기존 HTML/CSS 스타일만 담당한다.

## 자동 경로

`make_cards.py`가 다음 순서로 처리한다.

```text
ChatGPT/Codex JSON 답
  → check_cards (4~6장·필수 필드·아이콘)
  → unknown_terms (원문에 없는 영문·숫자)
  → build_spec (글 주제에 맞춘 밝은 카드 테마와 motion 선택)
  → render_cards
  → build_ready / render_motion_auto / Tesseract export
```

`make_cards.py --card-style comic_lavender`를 선택하면 카드 단계에서 `render_comic_cards.py`를 사용한다. 현재는 `cover`, `compare`, `steps`, `list` 레이아웃만 지원하며, 다른 레이아웃을 조용히 누락하지 않고 오류로 중단한다. 기본값인 `classic`은 기존 카드 렌더 경로를 유지한다. 만화형 카드의 글자는 PNG에 구워진 결과와 별개로 `.tsrct`의 편집 가능한 레이어이고, 제공받은 캐릭터 누끼 원본은 변형 없이 임베드한다. 배경만 별도 생성 이미지다.

결과:

```text
<post>/card-render/spec.json
<post>/card-render/cards/*.png
<post>/card-render/cards/preview.png
<post>/renders/motion-auto-<digest>/Motion-auto.tsrct
<post>/renders/reel-native-<digest>.mp4
<post>/renders/reel-native-<digest>-proof.png
<post>/renders/latest.json
```

카드 렌더는 폰트·넘침·충돌을 검사한다. 모션 렌더는 문구가 정해진 상자에 모두 들어가는지 검사하고 MP4의 크기·길이·FPS·오디오 유무를 확인한다. 이 검사는 미적 완성도를 판정하지 않는다.

자동 생성 MP4의 상태는 `draft_needs_design`이다. 이는 파일이 생성됐다는 뜻이지 승인된 디자인이라는 뜻이 아니다. 위젯의 검수 준비 영상으로 표시하지 않으며 자동 게시하지 않는다. 현재 자동 템플릿은 원글 전용 수작업 영상보다 시각적 밀도와 연출이 낮다. 카드별 디자인 검수를 거쳐야 게시 품질을 판단할 수 있다.

`motion_resolution`은 이전 원글의 수동 `.tsrct`를 보존하기 위한 호환 경로이며 새 게시물에는 선택되지 않는다. `motion`은 매번 카드 텍스트에서 별도 원본을 만든다. 두 경로 모두 효과음 전용일 때 음악 파일과 긴 오디오 레이어를 거부한다. Tesseract CLI 0.3.0과 그래픽 렌더링 환경이 필요하다.

모션 버전의 `portrait_preview`는 실제 MP4에서 추출한 1080×1920 세로 프레임이다. 여러 프레임을 가로로 붙인 `proof`는 내부 장면 검수용이며 릴스 표지나 비율 확인용으로 보여주지 않는다.

## 음원 결정

새 자동 모션 스펙은 아래처럼 음악 없는 효과음 전용으로 시작한다. 프로그램이 다른 주제에 기존 Jev 음원을 복제하지 않는다.

```json
{"audio": {"decision": "sfx_only", "reason": "음악 없이 주요 화면 전환에만 짧은 효과음"}}
```

기존 HTML 릴스는 승인 음원이 필요하다. 검수 후 프로젝트 안의 승인 파일을 선택하면 다음처럼 바꾼다.

```json
{"audio": {"decision": "approved", "file": "content/card-news/jev-2026-09-25/.tesseract-work/assets/jev-groove-mastered-30s-v2.wav"}}
```

무음이 내용상 필요한 경우에는 이유를 남긴다.

```json
{"audio": {"decision": "silent", "reason": "원글의 소리와 자막만 검수하는 버전"}}
```

`build_ready.py`의 기본 스캔은 음원이 아직 결정되지 않은 카드도 `awaiting_audio`로 출력하고 정상 종료한다. `renders/latest.json`도 같은 상태를 기록하므로, 이전 MP4가 현재 원고의 완성본처럼 보이지 않는다. 음원을 지정한 뒤 같은 스펙을 다시 실행하면 렌더 대기열에 다시 들어간다.

검수용 전체 카드 덱은 `samples/gallery/`, 실제 인코딩한 릴스 3종은 `samples/reels/`에 있다.

## 실제 원글 미디어

`card-render/spec.json`에 아래처럼 URL 없는 descriptor가 있으면 카드 표지와 릴스 배경에 실제 로컬 파일을 사용한다.

```json
{
  "media_root": "../source-media",
  "media": [
    {"type": "IMAGE", "file": "01.jpg", "sha256": "…", "fit": "contain", "label": "원글 이미지"}
  ]
}
```

허용 root는 `<post>/source-media/` 하나뿐이다. 절대경로·`..`·HTTP(S) URL은 거부하고 파일 형식·해시·이미지/영상 구조를 검사한다. 이미지/영상 바이트가 바뀌면 `build_ready.py`의 digest도 바뀌어 이전 MP4를 재사용하지 않는다. 자동 모션은 첫 카드부터 카드당 원글 미디어 하나씩 배경으로 쓰며, 카드 수보다 미디어가 많으면 누락을 막기 위해 실패한다.
