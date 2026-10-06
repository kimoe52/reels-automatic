# Threads 수집

Meta Threads의 연결된 본인 계정 게시물과 후속 댓글을 조회한다. 기존 블로그 자동화의 보안 환경파일을 읽고, 토큰을 이 폴더에 복사하지 않는다.

처리 상태는 `../state/`에 저장하고, 이미 처리한 게시물은 다시 만들지 않는다.

## 설정 확인

```bash
cd "/Users/kimmac/Documents/Project/돈 자동화/바이브코딩 릴스"
python3 automation/meta-threads/fetch/fetch_posts.py --check-only
```

실제 조회는 다음 명령으로 실행한다. 기존 블로그 자동화의 `THREADS_ACCESS_TOKEN`을 읽으며, 토큰을 이 프로젝트에 복사하지 않는다.

```bash
python3 automation/meta-threads/fetch/fetch_posts.py
```

조회 결과는 `snapshots/`에 저장된다. 새 글과 함께 기존 글의 후속 댓글 변경도 변환 단계로 넘긴다 (`new_count`, `updated_count` 구분).

일반 조회마다 `/me/replies`를 끝까지 읽어 늦게 작성한 후속 댓글도 확인한다.
작성자가 같고, `replied_to`가 원글 또는 이미 연결된 본인 댓글인 경우만 본문에 붙인다.
다른 사람의 댓글, 다른 사람 댓글에 달린 작성자의 답변, 다른 원글의 댓글은 붙이지 않는다.
원문 `source.json`은 보존하고 합친 원문·댓글 ID·연결 관계는 `source-thread.json`에 따로 둔다.
페이지 반복·다른 endpoint·권한 실패·20쪽 한도 초과는 완료로 처리하지 않고 수집 커서를 보존한다.

처음 실행할 때는 최신 페이지 한 장에서 멈추지 않고, 공식 same-origin 페이지 링크를
따라 과거의 마지막 페이지까지 가져온다. 이후 일반 실행은 저장된 시간 커서 이후의
새 글만 증분 수집한다. 과거 누락분을 다시 점검하려면 아래 옵션을 사용한다. 이미
state 또는 queue의 `source.json`에 있는 글은 미디어를 다시 받거나 중복으로 넘기지
않는다.

```bash
python3 automation/meta-threads/fetch/fetch_posts.py --backfill-history
# 일일 실행에서 수집·변환만 수행
python3 automation/meta-threads/run_daily.py --skip-cards --skip-render --backfill-history
```

한 실행은 최대 20쪽(`MAX_PAGES`)으로 제한된다. 잘못된 origin, 반복된 다음 링크,
또는 이 제한에 걸리면 종료 코드가 0이 아니며 커서와 `history_complete` 상태를
갱신하지 않는다. 마지막 과거 페이지까지 정상 완료한 경우에만
`history_complete: true`가 저장된다.

`401`이 나오면 설정 파일은 존재하지만 토큰이 만료된 것이다. 토큰을 채팅이나
이 폴더에 붙여 넣지 말고 기존 연결 도구에서 갱신한다.

```bash
cd "/Users/kimmac/Documents/Project/글쓰기 자동화/naver-blog-assistant"
./bin/app-marketing refresh-tokens
# 갱신 엔드포인트로 해결되지 않으면
./bin/app-marketing connect
```
