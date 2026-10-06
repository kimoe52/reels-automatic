# Meta Threads → 카드뉴스·릴스 자동화

이 작업의 원본은 X가 아니라 **Meta Threads의 `@sto.ckai` 계정**이다.

## 권장 흐름

```text
Meta Threads API
  → @sto.ckai 새 게시물 조회
  → 이어지는 글 묶기
  → 원문·날짜·링크 보존
  → ChatGPT 웹에서 카드 문안 JSON 작성
  → 원문 사실·구조·아이콘 검사
  → HTML/CSS로 4:5 카드 4~6장 렌더
  → 같은 스펙으로 20~30초 9:16 릴스 렌더
  → 카드·릴스 검수 대기 폴더 저장
```

Meta의 Threads API에는 인증된 사용자의 게시물 목록을 조회하는 `/me/threads` 흐름이 있고, 게시물 텍스트·링크·timestamp·permalink 같은 필드를 받을 수 있다. 새 글만 처리하려면 마지막으로 처리한 게시물 ID 또는 timestamp를 로컬 상태 파일에 저장한다.

## 콘텐츠 규칙

- 카드뉴스는 **4~6장**만 허용한다. 기본값은 5장.
- 카드 마지막 장에는 원문 permalink와 작성일을 표시한다.
- 원문에 없는 주가 전망·수치·매매 판단을 추가하지 않는다.
- 릴스는 카드 PNG를 여백에 넣지 않고, 카드와 같은 문안을 9:16 장면으로 다시 조판한다. 글마다 `band`(상단 제목+하단 자막), `bold`(큰 타이포+강한 컷), `list`(고정 제목+순차 목록) 중 하나를 순환한다.
- 카드 색은 `paper`, `mono`, `kraft`, `gray`, `mint`를 글마다 순환하되 한 묶음 안에서는 한 팔레트를 유지한다. 긴 정보글을 첫 문장 하나로 축약하거나 장식용 인물·타자음을 자동으로 넣지 않는다.
- Jev는 이번 Jev 소개 콘텐츠의 **주제**다. 새 게시물 변환 과정이나 다음 주제의 제작 판단에 자동 호출하지 않는다.
- 금융 관련 내용은 자동 게시하지 않고 검수 대기 상태로 둔다.

## 자동 업데이트 기본값

- 주기: 하루 1회
- 처리: 새 Threads 게시물만. 마지막 실행 뒤 새 글이 50개를 넘으면 다음 페이지까지 읽는다
- 복구: 변환은 최신 스냅샷 하나가 아니라 아직 변환하지 않은 스냅샷을 모두 처리한다. 변환이 실패한 스냅샷은 다음 실행에서 다시 처리하고, 끝난 스냅샷은 `state/transform_state.json`에 기록한다. 특정 스냅샷만 다시 만들려면 `transform_posts.py --snapshot 경로`를 쓴다
- 결과: 원문 전체를 배분한 카드 계획·이미지 생성 요청·릴스 대본 생성. 원문 전체가 별도로 제공된 게시물은 `transform/source-overrides/{post_id}.txt`를 우선 사용하고, API 수집본은 함께 보존
- 카드: 공백 빼고 300자 이상인 새 글을 한 번에 최대 3개까지 ChatGPT 웹에 자동으로 붙여넣고 보낸다. 답이 끝나면 코드블록의 복사 버튼만 누른다. 답을 화면에서 자동으로 읽어 오는 것은 OpenAI 약관이 금지해서 하지 않는다. 복사된 JSON은 원문 대조 검사(4~6장·레이아웃별 필드·아이콘·원문에 없는 영어 단어와 숫자)를 거쳐 `production/card_render/`가 카드 PNG를 그린다.
- 디자인: 첫 장 3종, 본문 9종, 마지막 장 2종을 내용에 따라 조합한다. 원문의 주제와 안정적인 해시로 밝은 카드 테마와 `band`·`list` 릴스 스타일을 고른다. 기존 `bold` 스펙도 밝은 배경으로 렌더한다.
- 릴스: 카드 스펙을 `hook`, 비교, 순차 목록, 큰 키워드, 타이핑 프롬프트, 순위, 저장 CTA 장면으로 다시 구성한다. 게시물별 음원이 승인되거나 이유를 적어 무음을 결정한 경우에만 1080×1920, 20~30초, 30fps MP4를 만든다. 미결정 상태는 `awaiting_audio`로 표시하고 완성 영상으로 세지 않는다.
- 카드 재시도: 검사에 떨어진 글은 다음 실행에서 한 번 더 시도한다. 이미 카드가 완성되어 음원이나 릴스 수정을 기다리는 글은 ChatGPT에 다시 보내지 않는다. 특정 글의 문안을 다시 만들려면 `python3 production/card_render/make_cards.py --post 글ID`를 쓰고, 카드 단계를 빼려면 `run_daily.py --skip-cards`를 쓴다.
- ChatGPT 답변 대기 기록이 있으면 다음 일일 실행은 새 질문을 보내지 않고 그 답을 이어받는다. `run_daily.py --resume-chatgpt`로 명시적으로 이어받을 수도 있다. 위젯과 터미널 실행은 잠금으로 겹치지 않게 한다
- 첫 실행 때 macOS가 자동 붙여넣기에 필요한 '손쉬운 사용' 권한을 묻는다. 허용하지 않으면 질문을 클립보드에 복사해 두고 알림으로 붙여넣기를 안내한다
- 카드 PNG와 스펙 검사가 끝난 패키지는 네이티브 세로 MP4와 인코딩 프레임 연락 시트까지 생성한다. MP4 생성은 CPU를 많이 쓰므로 한 패키지씩 실행한다.
- 게시: 자동 게시하지 않고 `automation/meta-threads/queue/YYYY-MM-DD/`에 저장

토큰이 유효해진 뒤에는 아래 한 명령으로 수집·변환·승인 패키지 렌더를 실행한다.

```bash
cd "/Users/kimmac/Documents/Project/돈 자동화/바이브코딩 릴스"
python3 automation/meta-threads/run_daily.py
```

토큰 호출 없이 이미 완성된 카드 스펙과 기존 승인 이미지 패키지를 릴스로 렌더하려면 `python3 automation/meta-threads/run_daily.py --only-render`를 실행한다. 새 글의 카드 제작을 웹 ChatGPT로 이어가려면 `--open-chatgpt`, 기존 카드 계획을 열려면 `--only-chatgpt`를 쓴다. Safari 자동 전송은 macOS 손쉬운 사용 권한을 허용한 뒤 동작한다. 프로그램은 ChatGPT 응답을 스크래핑하지 않으므로 답의 JSON 코드블록은 사용자가 복사 버튼으로 클립보드에 넣어야 한다. 자동 게시 단계는 없다.

Meta 앱과 Threads 사용자 인증이 필요하다. 토큰은 저장소나 채팅에 남기지 않고 서버 또는 일회성 로컬 환경변수로만 사용한다.

## 기존 블로그 자동화 연결 재사용

기존 `글쓰기 자동화/naver-blog-assistant`에 Meta 연결이 이미 있다. 현재 확인된 상태는 다음과 같다.

- 보안 환경파일: `~/Library/Application Support/AppMarketing/.env`
- Threads 토큰 키: `THREADS_ACCESS_TOKEN`
- API 기본 주소: `https://graph.threads.net/v1.0`
- 기존 코드가 지원하는 것: Threads 게시 (`POST /me/threads`, 필요 시 `/me/threads_publish`)
- 아직 필요한 것: 새 게시물 조회 (`GET /me/threads`)와 마지막 처리 위치 저장

새 기능은 토큰을 복사하거나 별도 `.env`를 만들지 않고 기존 보안 환경파일을 읽는다. 기존 앱 홍보 게시 기능과 릴스·카드뉴스 수집 기능은 서로 다른 작업으로 분리한다. 2026-09-23 기준 새 Threads 토큰으로 읽기 요청이 성공했고, 50개 게시물을 수집·변환했다.

출처: [Meta for Developers](https://developers.meta.com/), [Meta 공식 Threads API Postman 컬렉션](https://www.postman.com/meta/threads/documentation/dht3nzz/threads-api)

## 원글 이미지·영상 보존

수집은 Threads 미디어 개체의 `media_url`, `thumbnail_url`, `children`, `alt_text`를 요청한다. carousel의 자식 ID는 공식 개별 미디어 조회로 상세 필드를 받은 뒤 순서를 유지한다. 지원 필드는 [Meta Threads 미디어 가져오기 레퍼런스](https://developers.facebook.com/docs/threads/reference/media-retrieval)에서 확인한다.

변환 단계는 URL을 카드나 브라우저에 넘기지 않고 곧바로 `<post>/source-media/`에 다운로드한다. HTTPS·공개 IP·Content-Type·용량을 확인하고, Threads 토큰은 CDN 요청에 보내지 않는다. `manifest.json`에는 로컬 파일명·SHA-256·크기·해상도만 남기며 서명된 원격 URL은 `source.json`과 처리 완료 snapshot에서 제거한다. 미디어가 없거나 API가 URL을 주지 않으면 기존 텍스트형 카드·릴스로 돌아간다.

기존 queue 글의 미디어만 공식 API에서 다시 받으려면 게시물 ID를 지정한다. 수집 cursor는 바뀌지 않는다.

```bash
python3 automation/meta-threads/fetch/fetch_posts.py --backfill-media 17915652486256246
```

실제 파일이 있으면 카드 표지가 원글 이미지를 우선 사용하고, 릴스는 훅 직후 이미지 carousel 또는 로컬 영상을 크게 보여준다. 영상은 렌더 프레임 시점마다 로컬 파일을 seek하므로 결과가 반복 실행에서도 동일하다.

위 API 필드 설명은 Meta 공식 문서를 바탕으로 재서술했다.
