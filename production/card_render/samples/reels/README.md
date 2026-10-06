# 9:16 Reel style samples

같은 카드 스펙을 세로 릴스 문법으로 다시 구성한 검수용 샘플이다. 카드 PNG를 위아래 여백에 넣은 영상이 아니다.

| 파일 | 스타일 | 원본 스펙 | 특징 |
|---|---|---|---|
| `vllo-band.mp4` | `band` | `../gallery/vllo/spec.json` | 상단 질문 고정, 밝은 정보 화면, 하단 한 줄 자막 |
| `jev-bold.mp4` | `bold` | `../jev/spec.json` | 검정·강조색 컷, 큰 타이포, 외곽선 자막 |
| `study-list.mp4` | `list` | `../gallery/study/spec.json` | 질문 고정, 번호 목록이 한 항목씩 채워짐 |

각 MP4 옆의 `*-proof.png`는 인코딩된 영상에서 뽑은 장면별 최종 프레임이고, 같은 이름의 JSON은 장면 시간·검사 결과·실제 인코딩 규격을 기록한다. 모두 기본값은 무음이며 자동 게시하지 않는다.

다시 만들기:

```bash
cd "/Users/kimmac/Documents/Project/돈 자동화/바이브코딩 릴스/production/card_render"
python3 render_reel.py samples/gallery/vllo/spec.json --style band --output samples/reels/vllo-band.mp4
python3 render_reel.py samples/jev/spec.json --style bold --output samples/reels/jev-bold.mp4
python3 render_reel.py samples/gallery/study/spec.json --style list --output samples/reels/study-list.mp4
```
