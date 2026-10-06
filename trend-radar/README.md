# Jev 1회성 트렌드 배치

이번 릴스의 형식을 정하기 위한 일회성 Python/pip 작업 폴더입니다. `candidates.csv`는 이미 확인한 릴스 5개이고, `pandas`가 날짜·공개 반응 수를 기계적으로 정리한 뒤 Jev가 형식 적합성·재현성·증거 품질을 판단합니다. pandas가 아직 설치되지 않은 상태에서도 같은 정리 단계는 표준 라이브러리로 확인할 수 있습니다.

Jev 결과가 `locked-format.json`에 저장되면 이후 영상 제작은 그 결과를 고정 기준으로 사용합니다. 이 폴더를 정기 실행하거나 영상 제작 파이프라인에 연결하지 않습니다.

## 실행

```bash
cd "/Users/kimmac/Documents/Project/돈 자동화/바이브코딩 릴스/trend-radar"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
read -r -s "TYPESAFE_API_KEY?TypeSafe API key: "
export TYPESAFE_API_KEY
python run_once.py
unset TYPESAFE_API_KEY
deactivate
```

키는 저장소, `.env` 파일, 채팅에 남기지 않습니다. `locked-format.json`이 있으면 기본적으로 재호출하지 않으며, 실수로 반복 호출하지 않도록 `--overwrite`는 의도적으로 명시해야 합니다.
