# PromptGuard Demo v0 구현 및 검증 보고서

검증일: 2026-10-01 (Asia/Seoul)

## 1. 생성한 파일 구조

```text
promptguard/
  audit/logger.py
  common/location.py
  common/schema.py
  daemon/server.py
  decision/base.py
  decision/mock_predictor.py
  detector/rules.py
  hooks/hook.py
  redaction/engine.py
  runner/main.py
  scripts/start_daemon.ps1
  scripts/run_codex_demo.ps1
  tests/test_pipeline.py
synthetic_workspace/
  .env
  AGENTS.md
README.md
DEMO_V0_REPORT.md
```

transport, detector, decision, location/schema, redaction, audit, Hook, runner를 분리했다. operation 원문과 task 원문은 daemon 메모리에만 존재한다.

## 2. location.py 재사용 방식

요청에 언급된 구현 파일 `location.py`는 첨부물에 없었고, `test_location.py`만 제공됐다. 따라서 제공된 테스트를 규격의 source of truth로 삼아 공용 구현을 `promptguard/common/location.py` 한 곳에만 만들었다.

- runtime detector는 모든 candidate에 `locate()`를 호출한다.
- dataset 코드도 동일 모듈의 `locate`, `build_location`, `check_span`, `split_lines`, `window_text`를 import하도록 README에 명시했다.
- 별도의 runtime 위치 계산 로직은 없다.
- Python Unicode code-point offset, 무정규화, LF-only line split, CR 보존 규칙을 사용한다.

제공된 테스트 결과: **10 tests 통과, 12 cases × 2 window sizes 통과**. ASCII, 한글, NFD, emoji, CRLF, Unicode line separator, multiline value, minified long line을 포함한다.

## 3. candidate record 실제 shape

runtime의 `Candidate` 계약은 다음과 같다.

```json
{
  "candidate_id": "stdout-c2",
  "session_id": "<session-id>",
  "turn_id": "<turn-id>",
  "operation_id": "<operation-id>",
  "type": "PASSWORD",
  "text": "<raw value: memory only>",
  "span": {"start": 47, "end": 68},
  "line": {
    "first": 3,
    "last": 3,
    "text": "<original line: memory only>",
    "value_start": 12,
    "value_end": 33
  },
  "context": {
    "before": ["<nearby original lines: memory only>"],
    "after": ["<nearby original lines: memory only>"],
    "before_truncated": false,
    "after_truncated": false
  },
  "meta": {"line_crop_offset": 0},
  "source": {
    "channel": "tool_output",
    "stream": "stdout",
    "tool_name": "Bash"
  }
}
```

실제 Demo에서는 `PRIVATE_IP`, `PASSWORD`, `TOKEN` 후보 3개가 생성됐고 모든 span을 원문으로 역검증했다. raw `text`, line, context는 predictor 입력용 메모리 객체에만 존재하며 audit에는 저장하지 않는다.

## 4. predictor interface

`promptguard/decision/base.py`의 유일한 계약:

```python
predict(candidates, task_context) -> list[Prediction]
```

각 prediction은 `candidate_id`, `action` (`KEEP` 또는 `MASK`), `confidence`를 가진다. Demo의 `MockPredictor`는 다음처럼 deterministic하다.

- PASSWORD → MASK
- TOKEN → MASK
- PRIVATE_IP → KEEP

`task_context`는 UserPromptSubmit에서 daemon 메모리에 저장되고 runner까지 전달된다. Mock은 의도적으로 이를 사용하지 않지만 실제 모델은 같은 인자로 바로 사용할 수 있다.

## 5. Demo 흐름

1. UserPromptSubmit이 task를 daemon 메모리에 저장
2. PreToolUse가 Bash command를 daemon에 등록
3. daemon이 UUID operation ID를 반환
4. Hook이 command를 runner + UUID만 포함하도록 교체
5. runner가 operation을 one-time claim
6. child PowerShell의 stdout/stderr 분리 캡처
7. rule detector가 후보 생성
8. 공용 location.py가 span/line/context 계산
9. MockPredictor가 KEEP/MASK 결정
10. SHA-256 fingerprint 기반 session placeholder 할당
11. span 역순 치환으로 sanitized envelope 생성
12. child exit code 보존
13. PostToolUse가 envelope와 raw synthetic marker 부재 검증
14. Codex가 sanitized 결과로 task 완료

동일 session/type/raw value의 fingerprint는 daemon 메모리에서 같은 index로 매핑된다. 원문 자체는 placeholder map에 저장하지 않는다.

## 6. 실제 Codex CLI 테스트 결과

- Codex CLI 0.159.2, gpt-6.1-sol, Windows/PowerShell
- 자연어 task로 실제 `codex exec` 실행
- UserPromptSubmit task stored: 성공
- PreToolUse rewrite: 성공
- operation claim: 성공
- `.env` command exit: 0
- 후보: 3개 (`PRIVATE_IP`, `PASSWORD`, `TOKEN`)
- 결정: `KEEP`, `MASK`, `MASK`
- PostToolUse: verified
- 모델 task 완료: 성공
- 최종 marker: **`PROMPTGUARD_DEMO_V0_OK`**

Codex가 추가로 실행한 안전한 파일 목록 command도 같은 runner 경로를 통과했고 후보 0개, exit 0으로 정상 처리됐다.

## 7. sanitized output 예시

```text
[PROMPTGUARD_RESULT]
status=executed
exit_code=0
[stdout]
DB_HOST=10.20.30.15
DB_USER=deploy
DB_PASSWORD=[PASSWORD_1]
API_TOKEN=[TOKEN_1]
LOG_LEVEL=debug
[stderr]
```

private IP는 KEEP, password/token은 MASK가 적용됐다.

## 8. raw leakage 여부

최종 성공 실행에서:

- model-facing `codex exec --json` raw password marker: 없음
- model-facing `codex exec --json` raw token marker: 없음
- audit log raw prompt/command/output/candidate value: 없음
- audit에는 candidate count/type/action, IDs, status, latency, marker boolean만 존재
- PostToolUse `marker_present`: false
- Hook 출력 spill: 없음
- Codex 실행은 ephemeral로 수행해 rollout을 저장하지 않음

synthetic fixture 자체는 detector 입력이므로 의도적으로 합성 원문을 가진다. 이는 로그 유출과 구분한다.

## 9. latency

민감 후보 3개가 포함된 주 file-read operation:

- runner 내부 전체 처리: **791.84ms**
- daemon register부터 PostToolUse verified까지: 약 **3.65초**
- 실패: 0

추가 안전 command의 runner 처리 시간은 657.17ms였다. Demo v0에서는 최적화하지 않았고, Python/PowerShell/Hook 프로세스 시작 비용이 지배적이다.

## 10. 실제 팀원 모델 교체 지점

바꿀 부분은 두 곳뿐이다.

1. `promptguard/decision/base.py`의 `Predictor` protocol을 구현하는 팀원 inference adapter 추가
2. `promptguard/runner/main.py`의 `MockPredictor()` 생성 한 줄을 새 predictor factory 또는 adapter로 교체

daemon, Hook, detector, Candidate schema, location.py, redaction, runner envelope, PostToolUse verifier는 바꿀 필요가 없다. 팀원 모델은 raw candidate와 task context를 메모리에서 받고, candidate ID별 KEEP/MASK prediction만 반환하면 된다.

## 11. V1 task-aware relevance 최소 변경점

1. MockPredictor 대신 task-aware predictor 연결
2. UserPromptSubmit의 `task_context`를 모델 입력 feature로 변환
3. 현재 Candidate JSON과 공용 location 규격으로 dataset serializer 작성
4. offline evaluation에 KEEP/MASK label과 task pairing 추가
5. predictor timeout/error 시 MASK 또는 전체 withheld 중 정책 하나를 명시

transport나 Hook architecture를 다시 설계할 필요는 없다. GENERALIZE가 필요해지는 단계에서만 `Action` union과 redaction 결과 타입을 확장한다.

## 12. 현재 알려진 한계

- Demo rule detector는 password/private IP/합성 token 패턴만 지원한다.
- MockPredictor는 task relevance를 사용하지 않는다.
- KEEP/MASK만 있고 GENERALIZE는 없다.
- Windows/PowerShell/Codex CLI만 검증했다.
- hosted/specialized tool을 가로채지 않는다.
- Hook 자체의 crash/미적용 경로까지 강제하는 완전한 보안 경계가 아니다.
- loopback endpoint에 enterprise 인증/ACL이 없다.
- task와 command는 짧은 시간 daemon 메모리에 존재한다.
- stdout/stderr 전체를 runner 메모리에 캡처하므로 대용량 stream 최적화가 없다.
- 실제 ML 성능, 일반화, 경량화는 V1 이후 범위다.
