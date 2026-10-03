# Release Evidence v1

`REQ-OPS-101`, `INV-054`, ADR-KSI-032 RT-02의 release evidence는 한 번의 release
후보가 어떤 **깨끗한 Git commit**, 어떤 **로컬 KSI product image identity**, 어떤
SBOM/scanner bytes, 어떤 외부 runtime image pin을 사용했는지 기록하는 create-once
owner-only local envelope다.

이 도구는 배포기가 아니다. 취약점이 승인됐다는 뜻, scanner 결과가 허용됐다는 뜻,
이미지가 registry에 push됐다는 뜻, 고객 데이터 배포가 승인됐다는 뜻도 아니다. SHA-256
sidecar 역시 서명·WORM 보관·원격 anchor가 아니므로 authenticity 또는 tamper-proof를
제공하지 않는다. 그런 보장과 판정은 별도 보안·운영 release review의 책임이다.

## 입력과 경계

- CLI는 현재 Git worktree가 완전히 clean할 때만 `HEAD`의 40자리 SHA를 직접 읽는다.
  CLI에 SHA나 timestamp override는 없다.
- product image는 `ksi-core:2026.08.30.1@sha256:<64 hex>`처럼 사람이 읽을 수 있는
  정확한 `ksi-*` version tag와 digest를 모두 가져야 한다. `latest`, `stable`, tag-only,
  digest-only, 숫자가 없는 tag, 외부 vendor image는 거부한다.
- image마다 CycloneDX JSON SBOM 1개와 scanner JSON 1개가 모두 필요하다. 두 파일은
  절대경로의 일반 파일이어야 하고, Git worktree 안·symlink 경로·비정상/과대 JSON은
  거부한다.
- `tools/check_runtime_image_pins.py`와 그 대상 Dockerfile/Compose/script는 현재 live
  worktree가 아니라 manifest의 `source.gitCommitSha`가 가리키는 정확한 Git tree에서만
  안전하게 materialize해 검사한다. 따라서 source SHA와 runtime ref를 서로 다른
  worktree 상태에서 섞지 않는다. 이 gate가 실패하면 partial manifest를 만들지 않는다.
- 생성 디렉터리는 반드시 Git worktree 밖의 새 절대경로다. 기존 디렉터리를 덮어쓰지
  않으며 directory는 `0700`, manifest와 sidecar는 `0600`으로 만든다.

입력 JSON은 Linux `O_NOFOLLOW`와 directory/file descriptor로 한 번만 열어 regular-file
identity와 byte 길이를 `fstat`으로 전후 대조한다. 따라서 경로 검사 뒤 symlink 교체나
path swap이 일어나면 읽지 않고 거부한다. 출력도 symlink 없는 parent directory descriptor
아래에서 `O_NOFOLLOW|O_EXCL`로 생성하므로 manifest 경로가 승인된 새 directory 밖으로
바뀌지 않는다.

manifest에는 SBOM·scan의 내용이나 절대경로를 넣지 않는다. 안전한 basename, type,
byte 길이, SHA-256만 기록한다. 각 SBOM/scanner는 해당 product image 항목 아래에
구조적으로 연결되지만, 이 도구는 artifact bytes가 실제로 그 image에서 생성됐음을
증명하지 않는다. empty scanner object도 거부하지만, scanner의 적합성·서명·보관은
별도 release gate에서 검증해야 한다.

## 생성 절차

먼저 image를 로컬에서 build하고, 해당 image의 CycloneDX SBOM 및 scanner JSON을 이미
만든 상태여야 한다. 이 명령은 Docker나 network를 실행하지 않는다.

Inspector와 measurement는 각각 `Dockerfile.external-inspector`와
`Dockerfile.external-measurement`에서 독립적으로 build·scan한다. registry가 반환한 exact
repo digest가 생기기 전의 로컬 tag나 Docker image ID를 `@sha256:` release reference로
꾸며 넣어서는 안 된다. 두 runtime artifact는 product image release evidence와 별도로
host binding의 `runtimeProducts`에 들어가며, staging gate가 SBOM/scanner bytes와 실제
로컬 image identity를 다시 대조한다.

### Runtime scanner content compatibility

`tools/verify_external_scanner_evidence.py` verifies strict inspector/measurement scanner
bytes in the lifecycle. Existing nonempty `scanner.name`/`scanner.schemaVersion` envelopes
remain supported; genuine Grype0.120.0 JSON is also parsed directly. Native validation requires the supported
descriptor/DB profile, well-formed matches and exact `source.target.imageID` equality with
the independently verified host `dockerImageId`. Raw bytes are not rewritten, findings/ignores
are not dropped, and DBv6.1.10 is not presented as a report schema. The16MiB regular-file
reader hashes/parses one payload, rejects symlink traversal, changed files, duplicate keys,
non-finite values and malformed/ambiguous/unknown profiles. Core/Dashboard generic scanner
handling and canonical/host v1 wire shapes are unchanged.
Legacy envelopes retain their pre-existing external byte/hash/host association, not a new
in-report image proof. Incidental legacy source annotations do not make a document native;
Grype descriptor or structured source `type`/`target` fields identify native candidates.
Mixed/unsupported native candidates still fail closed. The unchanged generic Core/Dashboard
artifact path still hashes and parses through separate reads; no TOCTOU-hardening claim is
made for that path.

This equality rule is deliberately **not** an index-to-config converter. On the observed
Docker29 containerd store, `.Id` is the OCI index, `--platform` yields the platform manifest,
and the Grype scan ID is the config digest. These distinct identities fail equality. The
standalone consumer accepts a retained report with its archive-verified config ID, but that
does not establish a complete actual host/release binding. A separately reviewed image-link
contract is required before native reports can satisfy the gate on that store. Never fabricate
a host observation, reinterpret a manifest as a config, or use the report's own ID as its
expected trusted ID. Registry promotion, tool signatures, original DB bytes/freshness, security
disposition and live containment remain separate gates. Detailed verification is in
[local evidence](SPATIAL_DATA_LOCAL_VERIFICATION.md#python-repair-and-native-scanner-consumer--2026-10-04).

```bash
git status --short
# 반드시 출력이 없어야 한다.

uv run --locked python tools/build_release_evidence.py \
  --output-dir /srv/ksi-release-evidence/2026-08-30-r1 \
  --image-artifact \
  'ksi-core:2026.08.30.1@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' \
  /srv/ksi-release-inputs/ksi-core.cdx.json \
  /srv/ksi-release-inputs/ksi-core.scan.json \
  --image-artifact \
  'ksi-dashboard:2026.08.30.1@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' \
  /srv/ksi-release-inputs/ksi-dashboard.cdx.json \
  /srv/ksi-release-inputs/ksi-dashboard.scan.json
```

성공하면 아래 두 파일만 새 output directory에 생성한다.

- `release-evidence.json`: canonical JSON (`sort_keys`, compact separators, trailing newline)
- `release-evidence.json.sha256`: manifest의 SHA-256 sidecar

실패하면 새 output directory와 부분 파일을 삭제한다. cleanup 자체가 실패하면 tool은
residual output 경로를 포함한 typed error를 반환한다. 기존 directory는 시작 전에
거부하므로 기존 release evidence를 수정하거나 지우지 않는다.

## 검토 항목

release reviewer는 적어도 다음을 대조한다.

1. manifest `source.gitCommitSha`가 승인한 source commit인가.
2. product image ref의 tag와 digest가 build/registry promotion 기록과 일치하는가.
3. SBOM/scanner artifact hash가 별도 보관된 원본 bytes와 일치하는가.
4. `externalRuntimeImages`가 현재 deployment manifest 및
   `tools/check_runtime_image_pins.py` 결과와 일치하는가.
5. 취약점, 라이선스, 데이터 보관, cloud 승인, backup/restore, 운영자 승인 같은
   별도 release gate가 실제로 통과했는가. 이에는 signature/WORM/remote anchor와
   artifact-to-image provenance 검증도 포함한다.
