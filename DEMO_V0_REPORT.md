# PromptGuard CredSweeper Demo v0 검증 보고서

검증일: 2026-10-03 (Asia/Seoul)

## 1. 목적

기존 PromptGuard Hook + daemon + opaque operation ID + runner 구조에서
CredSweeper를 V0 credential detector로 사용하고, 실제 Codex가 받는 tool
output에는 credential value만 placeholder로 남는지 검증했다.

이 Demo는 rule-based credential masking의 end-to-end 동작을 증명한다.
task-aware relevance, ML 성능 또는 완전한 DLP coverage를 증명하지 않는다.

## 2. 구현

- dependency: `credsweeper==1.18.5`
- detector mode: `ml_threshold=0`, built-in filters enabled
- input: runner가 캡처한 stdout/stderr를 `StringContentProvider`로 메모리 스캔
- initial span: CredSweeper `LineData.value_start/value_end`
- normalization:
  - `URL Credentials` 같은 specialized rule 우선
  - 동일 URI 내부 generic candidate 제거
  - 겹치는 candidate 정규화
- policy: surviving credential candidate는 모두 `MASK`
- replacement: 오른쪽에서 왼쪽으로 placeholder 치환
- verification: PostToolUse에서 synthetic raw marker가 남으면 block

원본 tool output을 CredSweeper용 임시 파일로 저장하지 않는다. audit에는 ID,
상태, candidate count/type, action, latency, marker 존재 여부만 기록한다.

## 3. 실행 순서

```powershell
./promptguard/scripts/setup.ps1
./promptguard/scripts/start_daemon.ps1
./promptguard/scripts/run_codex_demo.ps1
```

`setup.ps1`는 repository-local `.venv`를 만들고 pinned CredSweeper를 설치한다.
Codex desktop bundled Python도 fallback으로 사용할 수 있다.

## 4. 테스트 결과

### 단위 테스트

3개 테스트 모두 통과했다.

1. CredSweeper candidate와 PromptGuard location/span 계약
2. PostgreSQL URI에서 password-only masking
3. MySQL URI의 generic `Secret=3306/app` 오탐 제거 및 port/database 보존

### 실제 Codex CLI E2E

- UserPromptSubmit task 저장: 성공
- PreToolUse command rewrite: 성공
- operation one-time claim: 성공
- child command exit code: 0
- CredSweeper candidates: 2개
- candidate types: `PASSWORD`, `PASSWORD`
- actions: `MASK`, `MASK`
- PostToolUse verifier: verified, raw marker 없음
- Codex task completion: 성공
- 최종 marker: `PROMPTGUARD_DEMO_V0_OK`

Model-facing 핵심 출력:

```text
DB_HOST=10.20.30.15
DB_USER=deploy
DB_PASSWORD=[PASSWORD_1]
DATABASE_URL=postgresql://admin:[PASSWORD_2]@prod-db.internal:5432/payments
LOG_LEVEL=debug
```

비밀번호 원문은 보이지 않았고, private IP, URL scheme, username, host, port,
database name은 유지됐다. Codex는 두 설정이 서로 다른 host/user를 가리킨다는
실제 구성 문제를 설명할 수 있었다.

## 5. E2E에서 발견하고 수정한 문제

초기 구현은 runner module import 시점에 CredSweeper를 먼저 로드했다. 이 import가
operation TTL보다 길어 operation이 claim 전에 만료됐다. runner가 operation을 즉시
claim한 다음 CredSweeper를 import하도록 순서를 바꿨다.

수정 후 모든 operation은 `claimed` 상태로 전환되고 command가 정상 실행됐다.
TTL을 임의로 늘리지 않아 one-time, short-lived operation 성질을 유지했다.

## 6. Leakage 확인

최종 E2E 실행 기준:

- model-facing tool result synthetic raw password marker: 없음
- audit log synthetic raw password marker: 없음
- audit log raw command/output/candidate value: 없음
- PostToolUse `marker_present`: false
- CredSweeper scan용 temp/spill file: 없음
- `.venv`, local `.env`, audit JSONL: Git 제외

합성 원문은 의도적으로 `.env.example` fixture에만 존재한다.

## 7. 성능

최종 E2E에서 runner 내부 처리 시간은 약 3.76~4.62초였다. 대부분은 매 tool call마다
새 runner process가 CredSweeper와 dependencies를 import하는 비용이다. 기능 검증용
V0에서는 허용하지만, 이후에는 daemon-side warmed detector 또는 장기 실행 worker로
옮겨야 한다. 이번 Demo에서는 아키텍처 범위를 늘리지 않았다.

## 8. 명확한 한계

- Windows/PowerShell/Codex CLI만 검증
- CredSweeper ML 기능 사용 안 함
- deterministic MASK policy이며 task-aware relevance 없음
- CredSweeper의 미탐·오탐 coverage를 해결하거나 완전하다고 주장하지 않음
- URI normalization은 V0에서 확인한 specialized/generic 충돌을 다루는 최소 구현
- hosted/specialized tool 전체를 가로채지 않음
- Hook 미적용 자체를 막는 완전한 보안 경계가 아님
- stdout/stderr 전체를 runner 메모리에 캡처
- process-per-call import latency가 큼

## 9. 판정

**V0 Demo 기반으로 사용 가능.**

CredSweeper를 candidate generator로 사용하고 PromptGuard가 span normalization과
redaction을 소유하는 구조가 실제 Codex Hook pipeline에서 동작했다. 다음 연구 단계는
인프라 확대가 아니라 이 candidate 위에서 task-aware KEEP/MASK relevance를 개발하고
평가하는 것이다.
