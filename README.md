# 바이브코딩 카드뉴스·릴스 자동화

Meta Threads `@sto.ckai`의 긴 글을 4~6장 카드뉴스와 20~30초 세로 릴스로 만드는 작업 폴더입니다. 자동 게시하지 않고 검수 대기 결과까지만 만듭니다.

## 구조

```text
바이브코딩 릴스/
├── 폴더 안내.md              # 완성본·원본·참고 자료를 찾는 안내
├── project-paths.json        # 위젯과 제작기가 공유하는 상대 경로 설정
├── .work/                   # 임시 작업과 정리 기록 (Finder 기본 숨김)
├── research/                 # 레퍼런스 관찰과 트렌드 판단 기준
├── trend-radar/              # pip 기반 Jev 1회성 배치
├── media/audio/              # 내레이션 등 제작 소재
├── automation/
│   └── meta-threads/          # 기존 Meta 연결을 이용한 Threads 수집·변환
│       ├── fetch/             # 새 게시물 조회
│       ├── transform/         # 카드뉴스·릴스 변환
│       ├── queue/             # 검수 대기 결과
│       └── state/             # 마지막 처리 위치
├── content/
│   ├── character/             # 사람형·뿔 달린 뱀·실사 레퍼런스 (실사 본인은 릴스 전용)
│   ├── card-news/             # 4~6장 카드뉴스 규칙·승인 이미지
│   └── reels/
│       ├── 완성 영상/          # 날짜·제목으로 찾는 검수 대기 MP4
│       ├── 검수 이미지/        # 영상과 같은 이름의 확인용 PNG
│       └── 제작 자료/          # 원본·배경·분리 요소·내부 작업 기록
└── production/
    ├── card_render/           # 4:5 카드 + 네이티브 9:16 릴스 HTML/CSS 렌더러
    ├── card_motion/           # 승인 카드의 요소별 HyperFrames 모션 릴스 + 이전 패키지 호환
    ├── flow/                  # Google Flow 소재 생성 메모·내보내기 위치
    └── vllo/                  # 공용 인코더와 이전 시안 보관
```

## 작업 순서

1. `automation/meta-threads/`가 새 Threads 글과 이어지는 글을 원문 그대로 수집한다.
2. ChatGPT 웹이 14개 카드 레이아웃 중 내용에 맞는 4~6장 문안 JSON을 만들고, 프로그램이 구조·아이콘·영문/숫자를 원문과 대조한다.
3. `production/card_render/render_cards.py`가 글마다 순환한 5개 테마 중 하나로 4:5 PNG를 만든다.
4. `production/card_render/render_reel.py`가 같은 문안을 9:16 장면으로 다시 조판한다. 게시물별 음원 또는 사유가 있는 무음 선택이 확정되면 MP4와 검수 연락 시트를 만든다.
5. 원문·작업 상태는 queue, 승인 카드 모음은 `content/card-news/generated/`, 릴스 완성본은 `content/reels/완성 영상/`에 저장한다. 게시·예약 업로드는 하지 않는다.

웹 ChatGPT에서 답변 복사가 아직 끝나지 않았다면 다음 실행은 기존 질문을 이어받는다. 위젯과 터미널에서 동시에 실행해도 한 작업만 진행한다. 승인된 이미지 카드로 만든 기존 릴스 패키지도 렌더 대상에 포함하되, 같은 글에 새 `card-render/spec.json`이 있으면 새 렌더러가 담당한다.

시나모롤 위젯의 `승인 카드 영상 만들기`는 가장 최근 승인한 카드 패키지를 직접 렌더한다. `카드 이미지로 릴스 만들기`는 밝은 일러스트 카드 PNG 4~12장만 받아 요소·배경 분리, 모션·읽기 시간·효과음 결정, HyperFrames MP4 출력까지 처리한다. 새 PNG 경로에는 수동 좌표가 필요 없다. 최신 영상과 등장 중간 프레임 검수 이미지는 위젯에서 열 수 있다. 사진·복잡한 배경 등 분리 불가 입력은 실패로 남기고 자동 게시하지 않는다.

디자인 전체 예시는 `production/card_render/samples/gallery/`, 릴스 3스타일 영상과 프레임은 `production/card_render/samples/reels/`에서 확인할 수 있습니다. 실행 방법은 [Threads 자동화 README](automation/meta-threads/README.md)와 [코드 렌더러 README](production/card_render/README.md)에 정리했습니다.

API 키와 `.env` 파일은 이 폴더에 저장하지 않습니다.

## 파일 정리 규칙

제작 파일과 임시 스크립트는 이 프로젝트 안에 저장합니다
전체 폴더 용도는 [폴더 안내](폴더%20안내.md)에 정리했습니다
위젯·Threads 큐·카드 라이브러리·릴스 제작기·임시 작업 경로는 `project-paths.json`에서 함께 관리합니다
프로젝트 안의 상대 경로만 허용하며 상위 폴더나 밖을 가리키는 링크는 저장 경로로 사용할 수 없습니다
위젯의 `릴스 폴더`는 `content/reels/완성 영상/`을 열고, 내부 해시 이름의 작업 폴더는 `제작 자료/`에만 만듭니다
완성 영상 이름은 `날짜_원문 제목_버전_검수대기.mp4`이며 검수 이미지는 같은 이름입니다
재정리 명령은 `python3 production/card_motion/storage.py --organize`입니다
기존 영상·원본은 삭제하지 않고 이전 프로그램 경로도 내부 호환 링크로 유지합니다

Safari의 개인 다운로드 설정은 변경하지 않습니다
프로그램이 이번 요청으로 새로 다운로드한 이미지에 한해서 저장·검증 후 프로젝트 안의 작업 폴더로 옮깁니다
기존 다운로드와 다른 파일은 건드리지 않습니다
모션효과 참고 이미지는 `research/reference-collection/모션효과 가이드/`에 모읍니다
사용자가 직접 만든 카드 디자인 참고 원본은 `content/card-news/references/주식 첫 투자/`에 보관합니다
이전 수동 시안 스크립트는 `production/vllo/이전 시안/`, 디자인 검토 문서는 `research/디자인 기획/`에 보관합니다
렌더·위젯 빌드 임시 파일은 프로젝트 안 `.work/`를 사용합니다

경로 점검은 `/opt/homebrew/bin/python3 production/organize_project.py`로 실행하며 파일을 이동하지 않습니다
알려진 이전 시안의 재정리는 같은 명령에 `--apply`를 붙입니다
기존 원문·검수 기록의 해시는 유지하고 이전 경로는 숨김 호환 링크로만 남깁니다

카드 렌더러는 Python 3.12 이상이 필요합니다. 위젯은 설치된 Homebrew Python을 사용하며, `run_daily.py`를 터미널의 오래된 `python3`로 실행해도 지원 버전이 설치돼 있으면 자동으로 전환합니다.
