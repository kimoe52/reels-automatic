# Threads 변환

수집한 원문을 카드뉴스와 릴스 검수 초안으로 변환한다. 일반 카드 계획은 4~6장이며, 긴 후속 원문은 별도 계획으로 최대 12장까지 배분한다. 읽기 어려울 정도로 길면 제작을 보류한다.

## 실행

최신 수집본을 자동 선택해 검수 대기 폴더에 결과를 만든다.

```bash
cd "/Users/kimmac/Documents/Project/돈 자동화/바이브코딩 릴스"
python3 automation/meta-threads/transform/transform_posts.py
```

카드 수는 원문 길이에 따라 4·5·6장으로 결정한다. 필요할 때만 `--cards 4`,
`--cards 5`, `--cards 6`으로 고정할 수 있다. 결과는 게시하지 않고
`automation/meta-threads/queue/YYYY-MM-DD/<post-id>/`에 둔다.

변환기는 원문 발췌와 검수용 표시만 만들며, 숫자·전망·매매 판단을 새로 생성하지 않는다.

`source-thread.json`은 본문과 연결이 검증된 본인 후속 댓글을 합친 자료다.
전체 원문 카드 배분은 `complete-thread-<digest>/card-plan.json`에 새로 저장한다.
원본 `source.json`, 기존 `card-plan.json`, 편집 문안, 기존 카드·영상은 덮어쓰지 않는다.
후속 댓글이 바뀌면 새로운 계획 경로가 만들어지고 위젯은 새 경로를 자동 선택한다.
사용자가 제공한 `source-full.txt`는 API 병합보다 우선한다.
