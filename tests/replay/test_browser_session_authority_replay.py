"""Core 로컬 세션 권한 — 실제 디스크 replay·동시성·보안 계약, 4차.

green≠작동 초점: 메모리 스텁이 아니라 실제 파일·실제 스레드·실제 AES-GCM·실제
fork 로 다음을 증명한다. lineage supersession(지연된 이전 의도 완성 거부·이전
세션 파기), 로그아웃의 의도 펜싱, 2단계 refresh 예약(새 토큰 발명 없음 — 보관
중인 실제 provider 토큰 반환·provider 가 준 실제 후계 저장·1승자·만료/모호함의
세션 영구 무효와 replay 금지·예약 일치 커밋만), 스냅샷 전체 AEAD(메타데이터
변조 거부), 쓰기 전 상한(최종 바이트 포함), 절대 경로·생성자 pid·모호한
부트스트랩 거부, 용량 예상 교체, close 뒤 모든 동작 거부, 평문·로그 비밀 누출
금지를 확인한다. 노출 엔드포인트는 없다(라이브러리 클래스만 다룬다).
"""

from __future__ import annotations

import contextlib
import os
import secrets
import signal
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from ksi_core.identity.browser_session_authority import (
    LineageCredential,
    LocalSessionAuthority,
    SessionAuthError,
    SessionAuthorityError,
    SessionConflictError,
    SessionCredential,
    SessionRecoveryError,
    generate_seal_key,
)

NOW = datetime(2026, 10, 29, 0, 0, 0, tzinfo=UTC)
SESSION_TTL = timedelta(hours=8)
INTENT_TTL = timedelta(minutes=10)
RETENTION = timedelta(days=7)
RESERVATION_TTL = timedelta(minutes=5)

PROVIDER_T0 = "provider-actual-token-t0-" + "x" * 24
PROVIDER_T1 = "provider-actual-token-t1-" + "y" * 24
PROVIDER_T2 = "provider-actual-token-t2-" + "z" * 24
BIG_TOKEN = "t" * 4096


def _open(
    directory: Path,
    *,
    seal_key: bytes | None = None,
    name: str = "browser-sessions.json",
    now: datetime = NOW,
) -> LocalSessionAuthority:
    return LocalSessionAuthority.open(
        directory / name,
        seal_key=seal_key if seal_key is not None else generate_seal_key(),
        session_ttl=SESSION_TTL,
        intent_ttl=INTENT_TTL,
        retention=RETENTION,
        refresh_reservation_ttl=RESERVATION_TTL,
        now=now,
    )


def _authority(
    tmp_path: Path, *, seal_key: bytes | None = None, now: datetime = NOW
) -> LocalSessionAuthority:
    return _open(tmp_path, seal_key=seal_key, now=now)


def _lineage(authority: LocalSessionAuthority, *, now: datetime = NOW) -> LineageCredential:
    return authority.create_lineage(now=now)


def _begin(
    authority: LocalSessionAuthority, lineage: LineageCredential, *, now: datetime = NOW
) -> str:
    return authority.begin_login(lineage.lineage_id, lineage.lineage_secret, now=now)


def _login(
    authority: LocalSessionAuthority,
    lineage: LineageCredential,
    principal: str = "operator-a",
    org: str = "org-a",
    *,
    now: datetime = NOW,
    refresh: str = PROVIDER_T0,
) -> tuple[SessionCredential, str]:
    nonce = _begin(authority, lineage, now=now)
    credential = authority.complete_login(nonce, principal, org, refresh, now=now)
    return credential, refresh


def test_relative_path_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SessionAuthorityError):
        LocalSessionAuthority.open(
            Path("relative-sessions.json"),
            seal_key=generate_seal_key(),
            session_ttl=SESSION_TTL,
            intent_ttl=INTENT_TTL,
            retention=RETENTION,
            refresh_reservation_ttl=RESERVATION_TTL,
            now=NOW,
        )
    assert not (tmp_path / "relative-sessions.json").exists()


def test_ambiguous_bootstrap_refuses_startup(tmp_path: Path) -> None:
    lock_path = tmp_path / "browser-sessions.json.lock"
    lock_path.touch()
    with pytest.raises(SessionRecoveryError):
        _authority(tmp_path)
    lock_path.unlink()
    tmp_file = tmp_path / "browser-sessions.json.tmp"
    tmp_file.write_bytes(b"partial")
    with pytest.raises(SessionRecoveryError):
        _authority(tmp_path)
    tmp_file.unlink()
    # 실패한 open 이 잠금 파일을 남겼을 수 있으니 둘 다 치운 뒤 열면 성공한다.
    lock_path.unlink(missing_ok=True)
    authority = _authority(tmp_path)
    try:
        assert authority.counts().sessions == 0
    finally:
        authority.close()


def test_whole_snapshot_replay_restores_across_restart(tmp_path: Path) -> None:
    seal_key = generate_seal_key()
    authority = _authority(tmp_path, seal_key=seal_key)
    lineage = _lineage(authority)
    credential, _ = _login(authority, lineage)
    pending = _begin(authority, lineage)
    authority.close()

    reopened = _authority(tmp_path, seal_key=seal_key)
    try:
        view = reopened.authenticate(
            credential.session_id,
            credential.session_secret,
            expected_principal_id="operator-a",
            expected_organization_id="org-a",
            now=NOW + timedelta(minutes=1),
        )
        assert view.lineage_id == lineage.lineage_id
        recovered = reopened.complete_login(pending, "operator-a", "org-a", PROVIDER_T1, now=NOW)
        assert recovered.session_id != credential.session_id
    finally:
        reopened.close()


def test_many_sessions_and_max_size_token_survive_restart(tmp_path: Path) -> None:
    seal_key = generate_seal_key()
    authority = _authority(tmp_path, seal_key=seal_key)
    lineages = [_lineage(authority) for _ in range(3)]
    credentials = [
        _login(authority, lineages[0], refresh=PROVIDER_T0)[0],
        _login(authority, lineages[1], refresh=BIG_TOKEN)[0],
        _login(authority, lineages[2], refresh=PROVIDER_T1)[0],
    ]
    reservation = authority.begin_refresh(
        credentials[0].session_id, credentials[0].session_secret, now=NOW
    )
    assert reservation.provider_refresh_token == PROVIDER_T0
    authority.complete_refresh(
        credentials[0].session_id,
        credentials[0].session_secret,
        reservation.reservation_id,
        PROVIDER_T2,
        now=NOW,
    )
    authority.close()

    reopened = _authority(tmp_path, seal_key=seal_key)
    try:
        assert reopened.counts().sessions == 3
        for credential in credentials:
            reopened.authenticate(credential.session_id, credential.session_secret, now=NOW)
        following = reopened.begin_refresh(
            credentials[0].session_id, credentials[0].session_secret, now=NOW
        )
        assert following.provider_refresh_token == PROVIDER_T2
        big = reopened.begin_refresh(
            credentials[1].session_id, credentials[1].session_secret, now=NOW
        )
        assert big.provider_refresh_token == BIG_TOKEN
        assert len(big.provider_refresh_token) == 4096
        # 상한을 넘는 토큰은 저장 전에 거부된다.
        nonce = _begin(reopened, lineages[2])
        with pytest.raises(SessionAuthorityError):
            reopened.complete_login(nonce, "operator-c", "org-a", "t" * 4097, now=NOW)
    finally:
        reopened.close()


def test_state_file_holds_no_plaintext_secrets_or_metadata(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    try:
        lineage = _lineage(authority)
        credential, _ = _login(authority, lineage)
        nonce = _begin(authority, lineage)
        reservation = authority.begin_refresh(
            credential.session_id, credential.session_secret, now=NOW
        )
        raw = (tmp_path / "browser-sessions.json").read_text(encoding="utf-8")
        for secret in (
            lineage.lineage_secret,
            credential.session_secret,
            PROVIDER_T0,
            nonce,
            reservation.reservation_id,
            reservation.provider_refresh_token,
        ):
            assert secret not in raw
        # 스냅샷 전체가 AEAD 밀봉이라 계정·주체 같은 메타데이터도 평문이 아니다.
        assert "operator-a" not in raw
        assert "provider-actual" not in raw
    finally:
        authority.close()


def test_begin_needs_no_identity_and_complete_binds_verified_principal(
    tmp_path: Path,
) -> None:
    authority = _authority(tmp_path)
    try:
        lineage = _lineage(authority)
        # 리다이렉트 전 begin 은 계정 없이 열린다.
        nonce = authority.begin_login(lineage.lineage_id, lineage.lineage_secret, now=NOW)
        credential = authority.complete_login(nonce, "operator-a", "org-a", PROVIDER_T0, now=NOW)
        view = authority.authenticate(credential.session_id, credential.session_secret, now=NOW)
        assert (view.principal_id, view.organization_id) == ("operator-a", "org-a")
        # 기대 계정과 검증된 계정이 다르면 묶지 않고 의도를 소진하지 않는다.
        nonce_b = authority.begin_login(lineage.lineage_id, lineage.lineage_secret, now=NOW)
        with pytest.raises(SessionAuthError):
            authority.complete_login(
                nonce_b,
                "operator-a",
                "org-a",
                PROVIDER_T1,
                now=NOW,
                expected_principal_id="operator-b",
            )
        recovered = authority.complete_login(nonce_b, "operator-a", "org-a", PROVIDER_T1, now=NOW)
        assert recovered.session_id != credential.session_id
    finally:
        authority.close()


def test_delayed_first_complete_is_refused_after_second_completes(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    try:
        lineage = _lineage(authority)
        nonce_a = _begin(authority, lineage)
        nonce_b = _begin(authority, lineage)
        credential_b = authority.complete_login(
            nonce_b, "operator-a", "org-a", PROVIDER_T0, now=NOW
        )
        # B 완성 뒤에 도착한 지연 A 완성은 거부된다 — A 는 권한이 되지 않는다.
        with pytest.raises(SessionAuthError):
            authority.complete_login(nonce_a, "operator-a", "org-a", PROVIDER_T1, now=NOW)
        assert authority.counts().sessions == 1
        view = authority.authenticate(credential_b.session_id, credential_b.session_secret, now=NOW)
        assert view.principal_id == "operator-a"
    finally:
        authority.close()


def test_second_complete_revokes_first_session_and_rejects_its_refresh(
    tmp_path: Path,
) -> None:
    authority = _authority(tmp_path)
    try:
        lineage = _lineage(authority)
        credential_a, _ = _login(authority, lineage, refresh=PROVIDER_T0)
        pending_a = authority.begin_refresh(
            credential_a.session_id, credential_a.session_secret, now=NOW
        )
        nonce_b = _begin(authority, lineage)
        credential_b = authority.complete_login(
            nonce_b, "operator-a", "org-a", PROVIDER_T1, now=NOW
        )
        # B 완성이 A 를 대체한다 — A 세션과 그 예약은 모두 죽는다.
        with pytest.raises(SessionAuthError):
            authority.authenticate(credential_a.session_id, credential_a.session_secret, now=NOW)
        with pytest.raises(SessionAuthError):
            authority.complete_refresh(
                credential_a.session_id,
                credential_a.session_secret,
                pending_a.reservation_id,
                PROVIDER_T2,
                now=NOW,
            )
        view = authority.authenticate(credential_b.session_id, credential_b.session_secret, now=NOW)
        assert view.principal_id == "operator-a"
        assert authority.counts().sessions == 1
    finally:
        authority.close()


def test_cross_account_and_cross_lineage_misuse_is_refused(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    try:
        lineage_one = _lineage(authority)
        lineage_two = _lineage(authority)
        credential_a, _ = _login(authority, lineage_one, "operator-a", "org-a")
        credential_b, _ = _login(authority, lineage_two, "operator-b", "org-a")
        with pytest.raises(SessionAuthError):
            authority.authenticate(credential_b.session_id, credential_a.session_secret, now=NOW)
        with pytest.raises(SessionAuthError):
            authority.authenticate(
                credential_a.session_id,
                credential_a.session_secret,
                expected_principal_id="operator-b",
                now=NOW,
            )
        with pytest.raises(SessionAuthError):
            authority.begin_login(lineage_one.lineage_id, lineage_two.lineage_secret, now=NOW)
        with pytest.raises(SessionAuthError) as excinfo:
            authority.authenticate("sess_missing", "x" * 43, now=NOW)
        assert "sess_missing" not in str(excinfo.value)
    finally:
        authority.close()


def test_logout_fences_pending_intents_and_rejects_pending_refresh(
    tmp_path: Path,
) -> None:
    authority = _authority(tmp_path)
    try:
        lineage = _lineage(authority)
        credential, _ = _login(authority, lineage, refresh=PROVIDER_T0)
        pending_intent = _begin(authority, lineage)
        pending_refresh = authority.begin_refresh(
            credential.session_id, credential.session_secret, now=NOW
        )
        authority.logout(credential.session_id, credential.session_secret, now=NOW)
        # 로그아웃 뒤 지연 의도 완성은 거부된다.
        with pytest.raises(SessionAuthError):
            authority.complete_login(pending_intent, "operator-a", "org-a", PROVIDER_T1, now=NOW)
        # 로그아웃 뒤 예약 완료도 거부된다.
        with pytest.raises(SessionAuthError):
            authority.complete_refresh(
                credential.session_id,
                credential.session_secret,
                pending_refresh.reservation_id,
                PROVIDER_T1,
                now=NOW,
            )
        # 같은 lineage 의 새 로그인은 막히지 않는다.
        credential_next, _ = _login(authority, lineage, refresh=PROVIDER_T1)
        view = authority.authenticate(
            credential_next.session_id, credential_next.session_secret, now=NOW
        )
        assert view.lineage_id == lineage.lineage_id
    finally:
        authority.close()


def test_forget_lineage_releases_everything(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    try:
        lineage = _lineage(authority)
        credential, _ = _login(authority, lineage)
        authority.forget_lineage(lineage.lineage_id, lineage.lineage_secret, now=NOW)
        with pytest.raises(SessionAuthError):
            authority.authenticate(credential.session_id, credential.session_secret, now=NOW)
        with pytest.raises(SessionAuthError):
            authority.begin_login(lineage.lineage_id, lineage.lineage_secret, now=NOW)
        assert authority.counts().lineages == 0
    finally:
        authority.close()


def test_begin_returns_actual_stored_provider_token(tmp_path: Path) -> None:
    """예약은 보관 중인 실제 provider 토큰을 돌려준다 — 발명하지 않는다."""
    authority = _authority(tmp_path)
    try:
        lineage = _lineage(authority)
        credential, stored = _login(authority, lineage, refresh=PROVIDER_T0)
        assert stored == PROVIDER_T0
        reservation = authority.begin_refresh(
            credential.session_id, credential.session_secret, now=NOW
        )
        assert reservation.provider_refresh_token == PROVIDER_T0
        assert reservation.reservation_id != PROVIDER_T0
    finally:
        authority.close()


def test_complete_stores_actual_provider_successor(tmp_path: Path) -> None:
    """완료는 provider 가 돌려준 실제 후계 토큰을 저장한다."""
    authority = _authority(tmp_path)
    try:
        lineage = _lineage(authority)
        credential, _ = _login(authority, lineage, refresh=PROVIDER_T0)
        reservation = authority.begin_refresh(
            credential.session_id, credential.session_secret, now=NOW
        )
        authority.complete_refresh(
            credential.session_id,
            credential.session_secret,
            reservation.reservation_id,
            PROVIDER_T1,
            now=NOW,
        )
        view = authority.authenticate(credential.session_id, credential.session_secret, now=NOW)
        assert view.generation == 2
        # 다음 예약은 발명된 토큰이 아니라 저장된 후계를 돌려준다.
        following = authority.begin_refresh(
            credential.session_id, credential.session_secret, now=NOW
        )
        assert following.provider_refresh_token == PROVIDER_T1
        authority.complete_refresh(
            credential.session_id,
            credential.session_secret,
            following.reservation_id,
            PROVIDER_T2,
            now=NOW,
        )
        third = authority.begin_refresh(credential.session_id, credential.session_secret, now=NOW)
        assert third.provider_refresh_token == PROVIDER_T2
    finally:
        authority.close()


def test_completion_requires_matching_reservation(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    try:
        lineage = _lineage(authority)
        credential, _ = _login(authority, lineage, refresh=PROVIDER_T0)
        reservation = authority.begin_refresh(
            credential.session_id, credential.session_secret, now=NOW
        )
        # 살아있는 예약이 있으면 새 예약은 충돌이다(세션은 산다).
        with pytest.raises(SessionConflictError):
            authority.begin_refresh(credential.session_id, credential.session_secret, now=NOW)
        # 예약 id 가 틀리면 커밋되지 않고 세션이 무효가 된다.
        with pytest.raises(SessionAuthError):
            authority.complete_refresh(
                credential.session_id,
                credential.session_secret,
                "r_" + secrets.token_urlsafe(24),
                PROVIDER_T1,
                now=NOW,
            )
        with pytest.raises(SessionAuthError):
            authority.authenticate(credential.session_id, credential.session_secret, now=NOW)
        assert reservation.reservation_id.startswith("r_")
    finally:
        authority.close()


def test_completed_reservation_cannot_be_reused(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    try:
        lineage = _lineage(authority)
        credential, _ = _login(authority, lineage, refresh=PROVIDER_T0)
        reservation = authority.begin_refresh(
            credential.session_id, credential.session_secret, now=NOW
        )
        authority.complete_refresh(
            credential.session_id,
            credential.session_secret,
            reservation.reservation_id,
            PROVIDER_T1,
            now=NOW,
        )
        # 성공 뒤 같은 완료의 재시는 살리지 않고 세션을 닫는다.
        with pytest.raises(SessionAuthError):
            authority.complete_refresh(
                credential.session_id,
                credential.session_secret,
                reservation.reservation_id,
                PROVIDER_T1,
                now=NOW,
            )
    finally:
        authority.close()


def test_concurrent_begin_has_exactly_one_winner(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    try:
        lineage = _lineage(authority)
        credential, _ = _login(authority, lineage, refresh=PROVIDER_T0)
        contenders = 8
        barrier = threading.Barrier(contenders)
        outcomes: list[str] = []
        guard = threading.Lock()

        def attempt() -> None:
            barrier.wait(timeout=10)
            try:
                reservation = authority.begin_refresh(
                    credential.session_id, credential.session_secret, now=NOW
                )
                result = f"won:{reservation.reservation_id}"
            except SessionConflictError:
                result = "lost"
            with guard:
                outcomes.append(result)

        threads = [threading.Thread(target=attempt) for _ in range(contenders)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert len(outcomes) == contenders
        winners = [outcome for outcome in outcomes if outcome.startswith("won:")]
        assert len(winners) == 1, outcomes
        # 승자가 provider 후계로 완료하면 다음 예약은 그 후계를 돌려준다.
        authority.complete_refresh(
            credential.session_id,
            credential.session_secret,
            winners[0].split("won:", 1)[1],
            PROVIDER_T1,
            now=NOW,
        )
        following = authority.begin_refresh(
            credential.session_id, credential.session_secret, now=NOW
        )
        assert following.provider_refresh_token == PROVIDER_T1
    finally:
        authority.close()


def test_crash_with_pending_reservation_kills_session_on_restart(tmp_path: Path) -> None:
    seal_key = generate_seal_key()
    authority = _authority(tmp_path, seal_key=seal_key)
    lineage = _lineage(authority)
    credential, _ = _login(authority, lineage, refresh=PROVIDER_T0)
    reservation = authority.begin_refresh(credential.session_id, credential.session_secret, now=NOW)
    # 완료 없이 재기동 — 모호한 예약이 남은 세션은 영구 무효다.
    authority.close()

    reopened = _authority(tmp_path, seal_key=seal_key)
    try:
        assert reopened.counts().sessions == 0
        assert reopened.counts().revocations == 1
        with pytest.raises(SessionAuthError):
            reopened.authenticate(credential.session_id, credential.session_secret, now=NOW)
        # 구 토큰 replay 도, 반환받았던 토큰으로 새 예약도 모두 거부된다.
        with pytest.raises(SessionAuthError):
            reopened.begin_refresh(credential.session_id, credential.session_secret, now=NOW)
        with pytest.raises(SessionAuthError):
            reopened.complete_refresh(
                credential.session_id,
                credential.session_secret,
                reservation.reservation_id,
                PROVIDER_T1,
                now=NOW,
            )
        # 같은 lineage 의 새 로그인은 막히지 않는다(세션만 죽고 lineage 는 산다).
        credential_next, _ = _login(authority=reopened, lineage=lineage, refresh=PROVIDER_T1)
        assert credential_next.session_id != credential.session_id
    finally:
        reopened.close()


def test_expired_reservation_invalidates_session_and_forbids_replay(
    tmp_path: Path,
) -> None:
    authority = _authority(tmp_path)
    try:
        lineage = _lineage(authority)
        credential, _ = _login(authority, lineage, refresh=PROVIDER_T0)
        reservation = authority.begin_refresh(
            credential.session_id, credential.session_secret, now=NOW
        )
        late = NOW + RESERVATION_TTL + timedelta(seconds=1)
        # 만료된 예약의 완료는 세션을 닫는다 — 재시도 없음.
        with pytest.raises(SessionAuthError):
            authority.complete_refresh(
                credential.session_id,
                credential.session_secret,
                reservation.reservation_id,
                PROVIDER_T1,
                now=late,
            )
        with pytest.raises(SessionAuthError):
            authority.authenticate(credential.session_id, credential.session_secret, now=late)
        # 구 토큰으로 새 예약을 여는 replay 도 거부된다.
        with pytest.raises(SessionAuthError):
            authority.begin_refresh(credential.session_id, credential.session_secret, now=late)
    finally:
        authority.close()


def test_timeout_direct_auth_invalidates_session(tmp_path: Path) -> None:
    """예약 만료 뒤 직접 인증만 와도 세션을 닫는다 — 읽기라고 살리지 않는다."""
    authority = _authority(tmp_path)
    try:
        lineage = _lineage(authority)
        credential, _ = _login(authority, lineage, refresh=PROVIDER_T0)
        authority.begin_refresh(credential.session_id, credential.session_secret, now=NOW)
        late = NOW + RESERVATION_TTL + timedelta(seconds=1)
        with pytest.raises(SessionAuthError):
            authority.authenticate(credential.session_id, credential.session_secret, now=late)
        assert authority.counts().sessions == 0
    finally:
        authority.close()


def test_expired_pending_without_purge_is_refused_at_next_begin(
    tmp_path: Path,
) -> None:
    authority = _authority(tmp_path)
    try:
        lineage = _lineage(authority)
        credential, _ = _login(authority, lineage, refresh=PROVIDER_T0)
        authority.begin_refresh(credential.session_id, credential.session_secret, now=NOW)
        late = NOW + RESERVATION_TTL + timedelta(seconds=1)
        # purge 없이 다음 begin 이 와도 만료 예약은 세션을 닫는다.
        with pytest.raises(SessionAuthError):
            authority.begin_refresh(credential.session_id, credential.session_secret, now=late)
        with pytest.raises(SessionAuthError):
            authority.authenticate(credential.session_id, credential.session_secret, now=late)
    finally:
        authority.close()


def test_wrong_reservation_id_invalidates_session(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    try:
        lineage = _lineage(authority)
        credential, _ = _login(authority, lineage, refresh=PROVIDER_T0)
        authority.begin_refresh(credential.session_id, credential.session_secret, now=NOW)
        with pytest.raises(SessionAuthError):
            authority.complete_refresh(
                credential.session_id,
                credential.session_secret,
                "r_" + secrets.token_urlsafe(24),
                PROVIDER_T1,
                now=NOW,
            )
        with pytest.raises(SessionAuthError):
            authority.authenticate(credential.session_id, credential.session_secret, now=NOW)
    finally:
        authority.close()


def test_capacity_reclaims_expired_lineages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ksi_core.identity.browser_session_authority as module

    monkeypatch.setattr(module, "_MAX_LINEAGES", 2)
    (tmp_path / "lineages").mkdir(mode=0o700)
    authority = _open(tmp_path / "lineages")
    try:
        _lineage(authority)
        _lineage(authority)
        with pytest.raises(SessionAuthorityError):
            authority.create_lineage(now=NOW)
        idle = NOW + RETENTION + timedelta(seconds=1)
        lineage = authority.create_lineage(now=idle)
        assert authority.counts().lineages == 1
        assert lineage.lineage_id.startswith("lin_")
    finally:
        authority.close()


def test_capacity_reclaims_expired_intents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import ksi_core.identity.browser_session_authority as module

    monkeypatch.setattr(module, "_MAX_INTENTS", 2)
    (tmp_path / "intents").mkdir(mode=0o700)
    authority = _open(tmp_path / "intents")
    try:
        lineage = _lineage(authority)
        _begin(authority, lineage)
        _begin(authority, lineage)
        with pytest.raises(SessionAuthorityError):
            _begin(authority, lineage)
        later = NOW + INTENT_TTL + timedelta(seconds=1)
        nonce = _begin(authority, lineage, now=later)
        credential = authority.complete_login(nonce, "operator-a", "org-a", PROVIDER_T0, now=later)
        assert credential.session_id.startswith("sess_")
    finally:
        authority.close()


def test_capacity_reclaims_expired_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ksi_core.identity.browser_session_authority as module

    monkeypatch.setattr(module, "_MAX_SESSIONS", 2)
    (tmp_path / "sessions").mkdir(mode=0o700)
    authority = _open(tmp_path / "sessions")
    try:
        lineage_one = _lineage(authority)
        lineage_two = _lineage(authority)
        _login(authority, lineage_one, "operator-a", "org-a", refresh=PROVIDER_T0)
        _login(authority, lineage_two, "operator-b", "org-a", refresh=PROVIDER_T1)
        assert authority.counts().sessions == 2
        # 같은 lineage 가 없는 새 lineage 완성은 여전히 거부된다.
        lineage_three = _lineage(authority)
        nonce_c = _begin(authority, lineage_three)
        with pytest.raises(SessionAuthorityError):
            authority.complete_login(nonce_c, "operator-c", "org-a", PROVIDER_T2, now=NOW)
        # 같은 lineage 대체는 제거 뒤 투영에 자리가 있어 허용된다.
        nonce = _begin(authority, lineage_one)
        credential_new = authority.complete_login(
            nonce, "operator-a", "org-a", PROVIDER_T2, now=NOW
        )
        assert credential_new.session_id.startswith("sess_")
        assert authority.counts().sessions == 2
        end = NOW + SESSION_TTL + timedelta(seconds=1)
        fresh = _begin(authority, lineage_one, now=end)
        credential = authority.complete_login(fresh, "operator-c", "org-a", PROVIDER_T2, now=end)
        assert authority.counts().sessions == 1
        assert credential.session_id.startswith("sess_")
    finally:
        authority.close()


def test_tampered_ciphertext_and_truncation_refuse_restart(tmp_path: Path) -> None:
    seal_key = generate_seal_key()
    authority = _authority(tmp_path, seal_key=seal_key)
    lineage = _lineage(authority)
    credential, _ = _login(authority, lineage, refresh=PROVIDER_T0)
    authority.close()
    state = tmp_path / "browser-sessions.json"
    raw = state.read_bytes()

    tampered = bytearray(raw)
    tampered[len(tampered) // 2] ^= 0x01
    state.write_bytes(bytes(tampered))
    with pytest.raises(SessionRecoveryError):
        _authority(tmp_path, seal_key=seal_key).close()

    state.write_bytes(raw[: len(raw) // 2])
    with pytest.raises(SessionRecoveryError):
        _authority(tmp_path, seal_key=seal_key).close()

    state.write_bytes(raw + b'trailing-garbage{"')
    with pytest.raises(SessionRecoveryError):
        _authority(tmp_path, seal_key=seal_key).close()

    # 키가 다르면(운영 키 교체·유출 키 폐기 상황) 복호가 실패하고 기동이 거부된다.
    state.write_bytes(raw)
    with pytest.raises(SessionRecoveryError):
        _authority(tmp_path, seal_key=generate_seal_key()).close()
    assert credential.session_id.startswith("sess_")


def test_fork_child_cannot_operate(tmp_path: Path) -> None:
    """fork 자식은 상속 flock 으로 동작할 수 없다 — 부모는 영향받지 않는다."""
    authority = _authority(tmp_path)
    lineage = _lineage(authority)
    credential, _ = _login(authority, lineage, refresh=PROVIDER_T0)
    pid = os.fork()
    if pid == 0:
        try:
            try:
                authority.authenticate(credential.session_id, credential.session_secret, now=NOW)
            except SessionRecoveryError:
                os._exit(0)
            else:
                os._exit(10)
        except BaseException:
            os._exit(11)
    _, status = os.waitpid(pid, 0)
    try:
        assert os.waitstatus_to_exitcode(status) == 0
        view = authority.authenticate(credential.session_id, credential.session_secret, now=NOW)
        assert view.principal_id == "operator-a"
    finally:
        authority.close()


def test_closed_instance_refuses_all_operations(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    lineage = _lineage(authority)
    credential, _ = _login(authority, lineage, refresh=PROVIDER_T0)
    nonce = _begin(authority, lineage)
    reservation = authority.begin_refresh(credential.session_id, credential.session_secret, now=NOW)
    authority.close()
    authority.close()  # 멱등 — 닫힌 뒤 닫기는 허용된다.
    refused = [
        lambda: authority.counts(),
        lambda: authority.create_lineage(now=NOW),
        lambda: authority.begin_login(lineage.lineage_id, lineage.lineage_secret, now=NOW),
        lambda: authority.complete_login(nonce, "operator-a", "org-a", PROVIDER_T1, now=NOW),
        lambda: authority.authenticate(credential.session_id, credential.session_secret, now=NOW),
        lambda: authority.begin_refresh(credential.session_id, credential.session_secret, now=NOW),
        lambda: authority.complete_refresh(
            credential.session_id,
            credential.session_secret,
            reservation.reservation_id,
            PROVIDER_T1,
            now=NOW,
        ),
        lambda: authority.logout(credential.session_id, credential.session_secret, now=NOW),
        lambda: authority.forget_lineage(lineage.lineage_id, lineage.lineage_secret, now=NOW),
        lambda: authority.purge_expired(NOW),
    ]
    for operation in refused:
        with pytest.raises(SessionRecoveryError):
            operation()


def test_second_writer_is_refused(tmp_path: Path) -> None:
    seal_key = generate_seal_key()
    first = _authority(tmp_path, seal_key=seal_key)
    try:
        with pytest.raises(SessionRecoveryError):
            _authority(tmp_path, seal_key=seal_key)
    finally:
        first.close()
    second = _authority(tmp_path, seal_key=seal_key)
    try:
        assert second.counts().sessions == 0
    finally:
        second.close()


def test_bounded_retention_purges_all_kinds(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    try:
        lineage_one = _lineage(authority)
        credential, _ = _login(authority, lineage_one, refresh=PROVIDER_T0)
        _begin(authority, lineage_one)
        report = authority.purge_expired(NOW + SESSION_TTL + timedelta(seconds=1))
        assert report.sessions == 1
        assert report.intents == 1

        later = NOW + SESSION_TTL + timedelta(seconds=2)
        lineage_two = _lineage(authority, now=later)
        credential_b, _ = _login(
            authority, lineage_two, "operator-b", "org-a", now=later, refresh=PROVIDER_T0
        )
        authority.logout(credential_b.session_id, credential_b.session_secret, now=later)
        credential_c, _ = _login(
            authority, lineage_two, "operator-c", "org-a", now=later, refresh=PROVIDER_T1
        )
        authority.begin_refresh(credential_c.session_id, credential_c.session_secret, now=later)
        # 예약 TTL 만료 뒤 정리 — 예약과 함께 세션도 영구 무효가 된다.
        mid = later + RESERVATION_TTL + timedelta(seconds=1)
        report = authority.purge_expired(mid)
        assert report.reservations == 1
        assert report.sessions == 1
        assert authority.counts().sessions == 0
        # 보존 기한 뒤 정리 — 파기 묘비와 유휴 lineage 가 사라진다.
        end = later + RETENTION + timedelta(seconds=2)
        report = authority.purge_expired(end)
        assert report.sessions == 0
        # 로그아웃 묘비와 만료 세션 표식이 보존 기한을 넘겼다 — 만료 예약 무효
        # 표식은 세션 만료가 더 늦어 아직 남는다.
        assert report.revocations == 2
        assert report.lineages == 2
        remaining = authority.counts()
        assert (remaining.sessions, remaining.revocations, remaining.lineages) == (0, 1, 0)
    finally:
        authority.close()


def test_errors_and_reprs_carry_no_secrets(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    try:
        lineage = _lineage(authority)
        credential, _ = _login(authority, lineage, refresh=PROVIDER_T0)
        nonce = _begin(authority, lineage)
        reservation = authority.begin_refresh(
            credential.session_id, credential.session_secret, now=NOW
        )
        assert credential.session_secret not in repr(credential)
        assert lineage.lineage_secret not in repr(lineage)
        assert reservation.provider_refresh_token not in repr(reservation)
        assert reservation.reservation_id not in repr(reservation)
        for outcome in (
            lambda: authority.authenticate("sess_nope", credential.session_secret, now=NOW),
            lambda: authority.authenticate(
                credential.session_id, "wrong-" + secrets.token_urlsafe(24), now=NOW
            ),
            lambda: authority.complete_login(
                "bogus-nonce", "operator-a", "org-a", PROVIDER_T0, now=NOW
            ),
            lambda: authority.complete_refresh(
                credential.session_id,
                credential.session_secret,
                "x",
                PROVIDER_T1,
                now=NOW,
            ),
        ):
            with pytest.raises(SessionAuthorityError) as excinfo:
                outcome()
            message = str(excinfo.value)
            for secret in (
                credential.session_secret,
                PROVIDER_T0,
                PROVIDER_T1,
                nonce,
                reservation.provider_refresh_token,
                reservation.reservation_id,
                lineage.lineage_secret,
            ):
                assert secret not in message
        # 잘못된 예약 완료는 세션을 닫는다 — 이후 동작도 비밀 없이 거부된다.
        with pytest.raises(SessionAuthError):
            authority.authenticate(credential.session_id, credential.session_secret, now=NOW)
    finally:
        authority.close()


def test_fork_child_close_closes_without_unlocking(tmp_path: Path) -> None:
    """fork 자식의 close 는 상속 fd 를 닫기만 하고 LOCK_UN 하지 않는다."""
    seal_key = generate_seal_key()
    authority = _authority(tmp_path, seal_key=seal_key)
    lineage = _lineage(authority)
    credential, _ = _login(authority, lineage, refresh=PROVIDER_T0)
    pid = os.fork()
    if pid == 0:
        try:
            authority.close()
        except BaseException:
            os._exit(10)
        os._exit(0)
    _, status = os.waitpid(pid, 0)
    try:
        assert os.waitstatus_to_exitcode(status) == 0
        # 부모 잠금은 그대로 — 같은 경로의 새 open 은 여전히 거부된다.
        with pytest.raises(SessionRecoveryError):
            _authority(tmp_path, seal_key=seal_key)
        view = authority.authenticate(credential.session_id, credential.session_secret, now=NOW)
        assert view.principal_id == "operator-a"
    finally:
        authority.close()


def _spawn_crashing_owner(
    tmp_path: Path, seal_key: bytes, *, child_closes: bool
) -> tuple[int, int, int, int]:
    """잠금을 쥔 owner 를 fork 로 만들고, 자식에게 복사본 정리 뒤 대기를 시킨다.

    (owner pid, 자식 pid, 자식 종료 신호 쓰기용 fd, 자식 상태 읽기용 fd)를
    돌려준다. 손자는 init 으로 reparent 되므로 waitpid 대신 상태 파이프로
    종료를 확인한다.
    """
    exit_r, exit_w = os.pipe()
    ready_r, ready_w = os.pipe()
    pid_r, pid_w = os.pipe()
    status_r, status_w = os.pipe()
    owner = os.fork()
    if owner != 0:
        # P: 자식 pid·상태만 읽고, 종료 신호만 보낸다.
        os.close(exit_r)
        os.close(ready_r)
        os.close(ready_w)
        os.close(pid_w)
        os.close(status_w)
        try:
            child_raw = os.read(pid_r, 32)
        finally:
            os.close(pid_r)
        return owner, int(child_raw.decode()), exit_w, status_r
    try:
        # O: 저장소를 먼저 열어 잠금 fd 를 확보한 뒤, 자식에게 필요 없는 끝만
        # 닫는다. 닫은 번호가 잠금 fd 로 재사용되면 자식이 엉뚱한 fd 를 닫는다.
        owner_auth = _authority(tmp_path, seal_key=seal_key)
        owner_lineage = _lineage(owner_auth)
        _login(owner_auth, owner_lineage, refresh=PROVIDER_T0)
        # 자식(C)은 ready 쓰기·상태 쓰기·exit 읽기만 쓴다 — 나머지만 닫는다.
        os.close(exit_w)
        os.close(pid_r)
        os.close(status_r)
        child = os.fork()
        if child == 0:
            try:
                os.close(ready_r)
                os.close(pid_w)
                if child_closes:
                    owner_auth.close()
                os.write(ready_w, b"1")
                os.close(ready_w)
                assert os.read(exit_r, 1) == b"1"
                os.close(exit_r)
                os.write(status_w, b"0")
            except BaseException:
                with contextlib.suppress(OSError):
                    os.write(status_w, b"1")
                os._exit(11)
            finally:
                with contextlib.suppress(OSError):
                    os.close(status_w)
            os._exit(0)
        os.write(pid_w, str(child).encode())
        os.close(pid_w)
        assert os.read(ready_r, 1) == b"1"
        os.close(ready_r)
        os.close(ready_w)
        os.close(exit_r)
        os.close(status_w)
        # close 없이 죽는다 — crash 를 재현한다.
        os._exit(99)
    except BaseException:
        os._exit(12)
    raise AssertionError("unreachable")  # pragma: no cover - 자식은 위에서 종료된다


def _reopen_after_crash(
    tmp_path: Path, seal_key: bytes, *, timeout_s: float = 10.0
) -> LocalSessionAuthority:
    """crash 뒤 잠금이 풀릴 때까지 재시도한다 — 상태 바이트가 파이프에 닿아도
    자식의 실제 종료는 그 뒤이므로 즉시 열기가 경합할 수 있다."""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            return _authority(tmp_path, seal_key=seal_key)
        except SessionRecoveryError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.02)


def test_parent_crash_with_surviving_closed_child_releases_lock(tmp_path: Path) -> None:
    """복사본을 닫은 자식이 살아있어도 owner crash 뒤 잠금이 풀린다."""
    seal_key = generate_seal_key()
    owner, child, exit_w, status_r = _spawn_crashing_owner(tmp_path, seal_key, child_closes=True)
    assert child > 0
    try:
        _, owner_status = os.waitpid(owner, 0)
        assert os.waitstatus_to_exitcode(owner_status) == 99
        reopened = _reopen_after_crash(tmp_path, seal_key)
        try:
            assert reopened.counts().sessions == 1
        finally:
            reopened.close()
    finally:
        with contextlib.suppress(OSError):
            os.write(exit_w, b"1")
        os.close(exit_w)
        try:
            child_status = os.read(status_r, 1)
        finally:
            os.close(status_r)
        assert child_status == b"0"


def test_parent_crash_with_fd_holding_child_keeps_lock(tmp_path: Path) -> None:
    """복사본을 쥔 자식이 살아있으면 owner crash 뒤에도 잠금이 유지된다."""
    seal_key = generate_seal_key()
    owner, child, exit_w, status_r = _spawn_crashing_owner(tmp_path, seal_key, child_closes=False)
    assert child > 0
    try:
        _, owner_status = os.waitpid(owner, 0)
        assert os.waitstatus_to_exitcode(owner_status) == 99
        # 자식이 fd 를 쥐고 살아있으므로 잠금은 풀리지 않는다.
        with pytest.raises(SessionRecoveryError):
            _authority(tmp_path, seal_key=seal_key)
    finally:
        with contextlib.suppress(OSError):
            os.write(exit_w, b"1")
        os.close(exit_w)
        try:
            child_status = os.read(status_r, 1)
        finally:
            os.close(status_r)
        assert child_status == b"0"
    # 자식이 죽으면(fd 커널 회수) 잠금이 풀린다.
    reopened = _reopen_after_crash(tmp_path, seal_key)
    try:
        assert reopened.counts().sessions == 1
    finally:
        reopened.close()


def test_fork_child_with_held_mutex_does_not_deadlock(tmp_path: Path) -> None:
    """뮤텍스를 쥔 채 fork 되어도 자식은 pid 검사에서 즉시 거부된다."""
    authority = _authority(tmp_path)
    authority._mutex.acquire()
    try:
        pid = os.fork()
        if pid == 0:
            try:
                signal.alarm(10)
                try:
                    authority.counts()
                except SessionRecoveryError:
                    os._exit(0)
                else:
                    os._exit(10)
            except BaseException:
                os._exit(11)
        _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 0
    finally:
        authority._mutex.release()
    try:
        assert authority.counts().sessions == 0
    finally:
        authority.close()


def test_tmp_blocked_seals_instance_and_preserves_disk(tmp_path: Path) -> None:
    """임시 파일 생성 실패도 봉인으로 닫는다 — 이후 동작 전부 거부, 디스크 intact."""
    seal_key = generate_seal_key()
    authority = _authority(tmp_path, seal_key=seal_key)
    _lineage(authority)
    (tmp_path / "browser-sessions.json.tmp").mkdir()  # tmp 생성 차단 — chmod 없이
    with pytest.raises(SessionRecoveryError):
        authority.create_lineage(now=NOW)
    # 봉인 — 이후 모든 동작 거부된다.
    with pytest.raises(SessionRecoveryError):
        authority.counts()
    with pytest.raises(SessionRecoveryError):
        authority.create_lineage(now=NOW)
    authority.close()
    (tmp_path / "browser-sessions.json.tmp").rmdir()
    reopened = _authority(tmp_path, seal_key=seal_key)
    try:
        # 실패한 생성은 디스크에 남지 않았다.
        assert reopened.counts().lineages == 1
    finally:
        reopened.close()


def test_oversize_write_seals_instance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """상한 초과 쓰기도 봉인으로 닫는다 — 이후 동작 전부 거부, 디스크 intact."""
    import ksi_core.identity.browser_session_authority as module

    seal_key = generate_seal_key()
    authority = _authority(tmp_path, seal_key=seal_key)
    monkeypatch.setattr(module, "_MAX_PLAINTEXT_BYTES", 0)
    with pytest.raises(SessionRecoveryError, match="상한 초과"):
        authority.create_lineage(now=NOW)
    with pytest.raises(SessionRecoveryError):
        authority.counts()
    authority.close()
    reopened = _authority(tmp_path, seal_key=seal_key)
    try:
        assert reopened.counts().lineages == 0
    finally:
        reopened.close()


def test_logout_after_reservation_timeout_revokes_and_fences(tmp_path: Path) -> None:
    """예약 만료 뒤 로그아웃도 허가된다 — 원자적으로 파기+펜싱한다."""
    authority = _authority(tmp_path)
    try:
        lineage = _lineage(authority)
        credential, _ = _login(authority, lineage, refresh=PROVIDER_T0)
        pending_intent = _begin(authority, lineage)
        pending_refresh = authority.begin_refresh(
            credential.session_id, credential.session_secret, now=NOW
        )
        late = NOW + RESERVATION_TTL + timedelta(seconds=1)
        # 만료 뒤에도 로그아웃은 성공해야 한다(거부가 아니다).
        authority.logout(credential.session_id, credential.session_secret, now=late)
        assert authority.counts().sessions == 0
        # 기존 의도는 펜싱됐다.
        with pytest.raises(SessionAuthError):
            authority.complete_login(pending_intent, "operator-a", "org-a", PROVIDER_T1, now=late)
        # 예약 완료도 거부된다.
        with pytest.raises(SessionAuthError):
            authority.complete_refresh(
                credential.session_id,
                credential.session_secret,
                pending_refresh.reservation_id,
                PROVIDER_T1,
                now=late,
            )
        # 같은 lineage 의 새 로그인은 막히지 않는다.
        credential_next, _ = _login(authority, lineage, refresh=PROVIDER_T1, now=late)
        view = authority.authenticate(
            credential_next.session_id, credential_next.session_secret, now=late
        )
        assert view.lineage_id == lineage.lineage_id
    finally:
        authority.close()


def test_same_lineage_replacement_allowed_at_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """같은 lineage 대체는 상한에서도 허용된다 — 제거 뒤 투영에 자리가 있다."""
    import ksi_core.identity.browser_session_authority as module

    monkeypatch.setattr(module, "_MAX_SESSIONS", 2)
    authority = _authority(tmp_path)
    try:
        lineage_one = _lineage(authority)
        lineage_two = _lineage(authority)
        credential_a, _ = _login(authority, lineage_one, "operator-a", "org-a", refresh=PROVIDER_T0)
        credential_b, _ = _login(authority, lineage_two, "operator-b", "org-a", refresh=PROVIDER_T1)
        assert authority.counts().sessions == 2
        nonce = _begin(authority, lineage_one)
        credential_new = authority.complete_login(
            nonce, "operator-a", "org-a", PROVIDER_T2, now=NOW
        )
        assert authority.counts().sessions == 2
        view = authority.authenticate(
            credential_new.session_id, credential_new.session_secret, now=NOW
        )
        assert view.principal_id == "operator-a"
        # 대체된 이전 세션은 죽고, 다른 lineage 세션은 살아있다.
        with pytest.raises(SessionAuthError):
            authority.authenticate(credential_a.session_id, credential_a.session_secret, now=NOW)
        view_b = authority.authenticate(
            credential_b.session_id, credential_b.session_secret, now=NOW
        )
        assert view_b.principal_id == "operator-b"
        # 같은 lineage 가 없는 새 lineage 완성은 여전히 거부된다.
        lineage_three = _lineage(authority)
        nonce_c = _begin(authority, lineage_three)
        with pytest.raises(SessionAuthorityError):
            authority.complete_login(nonce_c, "operator-c", "org-a", PROVIDER_T2, now=NOW)
    finally:
        authority.close()


def test_group_writable_ancestor_is_refused(tmp_path: Path) -> None:
    """그룹 쓰기 조상(775 계열) 아래 저장소는 거부된다 — chmod 없이 umask 로 재현."""
    old_umask = os.umask(0o002)
    try:
        wide = tmp_path / "wide"
        wide.mkdir()
    finally:
        os.umask(old_umask)
    assert wide.stat().st_mode & 0o020
    with pytest.raises(SessionRecoveryError):
        _open(wide)
    assert not (wide / "browser-sessions.json").exists()


def test_group_readable_state_file_is_refused(tmp_path: Path) -> None:
    """그룹 읽기 파일(0644 계열)은 복호 전에 거부된다 — umask 로만 재현."""
    seal_key = generate_seal_key()
    first = _open(tmp_path, seal_key=seal_key, name="src.json")
    try:
        lineage = _lineage(first)
        _login(first, lineage, refresh=PROVIDER_T0)
    finally:
        first.close()
    raw = (tmp_path / "src.json").read_bytes()
    old_umask = os.umask(0o022)
    try:
        fd = os.open(tmp_path / "dst.json", os.O_CREAT | os.O_WRONLY, 0o666)
        try:
            os.write(fd, raw)
        finally:
            os.close(fd)
    finally:
        os.umask(old_umask)
    assert (tmp_path / "dst.json").stat().st_mode & 0o040
    with pytest.raises(SessionRecoveryError):
        _open(tmp_path, seal_key=seal_key, name="dst.json")


def test_directory_state_path_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SessionRecoveryError):
        LocalSessionAuthority.open(
            tmp_path,
            seal_key=generate_seal_key(),
            session_ttl=SESSION_TTL,
            intent_ttl=INTENT_TTL,
            retention=RETENTION,
            refresh_reservation_ttl=RESERVATION_TTL,
            now=NOW,
        )


def test_logout_after_expiry_invalidation_fences_pending_intents(tmp_path: Path) -> None:
    """무효 뒤의 로그아웃도 허가되고 대기 의도를 펜싱한다 — 표식이 자격을 증명한다."""
    authority = _authority(tmp_path)
    try:
        lineage = _lineage(authority)
        credential, _ = _login(authority, lineage, refresh=PROVIDER_T0)
        pending = _begin(authority, lineage)
        authority.begin_refresh(credential.session_id, credential.session_secret, now=NOW)
        late = NOW + RESERVATION_TTL + timedelta(seconds=1)
        # 만료 예약 접촉이 세션을 무효로 닫는다 — 의도는 아직 펜싱되지 않았다.
        with pytest.raises(SessionAuthError):
            authority.authenticate(credential.session_id, credential.session_secret, now=late)
        assert authority.counts().sessions == 0
        # 죽은 자격으로도 로그아웃은 허가되고 의도를 펜싱한다.
        authority.logout(credential.session_id, credential.session_secret, now=late)
        with pytest.raises(SessionAuthError):
            authority.complete_login(pending, "operator-a", "org-a", PROVIDER_T1, now=late)
        # 표식은 소진됐다 — 같은 로그아웃 재시는 거부된다.
        with pytest.raises(SessionAuthError):
            authority.logout(credential.session_id, credential.session_secret, now=late)
        # 같은 lineage 의 새 로그인은 막히지 않는다.
        credential_next, _ = _login(authority, lineage, refresh=PROVIDER_T1, now=late)
        view = authority.authenticate(
            credential_next.session_id, credential_next.session_secret, now=late
        )
        assert view.lineage_id == lineage.lineage_id
    finally:
        authority.close()


def test_logout_on_time_expired_session_fences_pending_intents(tmp_path: Path) -> None:
    """세션 만료 뒤의 로그아웃도 허가되고 대기 의도를 펜싱한다."""
    authority = _authority(tmp_path)
    try:
        lineage = _lineage(authority)
        credential, _ = _login(authority, lineage, refresh=PROVIDER_T0)
        pending = _begin(authority, lineage)
        end = NOW + SESSION_TTL + timedelta(seconds=1)
        authority.logout(credential.session_id, credential.session_secret, now=end)
        assert authority.counts().sessions == 0
        with pytest.raises(SessionAuthError):
            authority.complete_login(pending, "operator-a", "org-a", PROVIDER_T1, now=end)
        credential_next, _ = _login(authority, lineage, refresh=PROVIDER_T1, now=end)
        view = authority.authenticate(
            credential_next.session_id, credential_next.session_secret, now=end
        )
        assert view.lineage_id == lineage.lineage_id
    finally:
        authority.close()


def test_missing_parent_is_refused_without_mkdir(tmp_path: Path) -> None:
    """없는 부모는 만들지 않고 거부된다 — 호출자가 owner-private 부모를 준비한다."""
    with pytest.raises(SessionRecoveryError):
        _open(tmp_path / "no-such-dir")
    assert not (tmp_path / "no-such-dir").exists()


def test_symlink_state_path_is_refused(tmp_path: Path) -> None:
    """심볼릭 재지정 상태 경로는 열기 전에 거부된다."""
    target = tmp_path / "real.json"
    target.write_bytes(b"{}")
    link = tmp_path / "link.json"
    os.symlink(target, link)
    with pytest.raises(SessionRecoveryError):
        LocalSessionAuthority.open(
            link,
            seal_key=generate_seal_key(),
            session_ttl=SESSION_TTL,
            intent_ttl=INTENT_TTL,
            retention=RETENTION,
            refresh_reservation_ttl=RESERVATION_TTL,
            now=NOW,
        )


def test_stale_marker_logout_cannot_fence_newer_session(tmp_path: Path) -> None:
    """무효 표식 세대의 로그아웃은 새 완성 뒤 펜싱하지 못하고 거부된다 — 재기동 포함."""
    seal_key = generate_seal_key()
    authority = _authority(tmp_path, seal_key=seal_key)
    lineage = _lineage(authority)
    credential_a, _ = _login(authority, lineage, refresh=PROVIDER_T0)
    authority.begin_refresh(credential_a.session_id, credential_a.session_secret, now=NOW)
    authority.close()

    reopened = _authority(tmp_path, seal_key=seal_key)
    try:
        assert reopened.counts().sessions == 0
        nonce_b = reopened.begin_login(lineage.lineage_id, lineage.lineage_secret, now=NOW)
        credential_b = reopened.complete_login(nonce_b, "operator-b", "org-a", PROVIDER_T1, now=NOW)
        pending_c = reopened.begin_login(lineage.lineage_id, lineage.lineage_secret, now=NOW)
        # A 표식 세대가 완성된 B 세대보다 오래됐다 — A 로그아웃은 거부된다.
        with pytest.raises(SessionAuthError):
            reopened.logout(credential_a.session_id, credential_a.session_secret, now=NOW)
        # B 시대 의도는 펜싱되지 않았다.
        credential_c = reopened.complete_login(
            pending_c, "operator-c", "org-a", PROVIDER_T2, now=NOW
        )
        assert credential_c.session_id != credential_b.session_id
        assert reopened.counts().sessions == 1
    finally:
        reopened.close()


def test_superseded_live_stale_logout_cannot_fence(tmp_path: Path) -> None:
    """대체로 사라진 세션의 로그아웃은 거부된다 — 새 시대 의도가 산다."""
    authority = _authority(tmp_path)
    try:
        lineage = _lineage(authority)
        credential_a, _ = _login(authority, lineage, refresh=PROVIDER_T0)
        nonce_b = _begin(authority, lineage)
        _login_output = authority.complete_login(
            nonce_b, "operator-b", "org-a", PROVIDER_T1, now=NOW
        )
        assert _login_output.session_id != credential_a.session_id
        pending_c = _begin(authority, lineage)
        # A 는 대체로 사라졌고 표식도 없다 — 로그아웃은 거부된다.
        with pytest.raises(SessionAuthError):
            authority.logout(credential_a.session_id, credential_a.session_secret, now=NOW)
        recovered = authority.complete_login(pending_c, "operator-c", "org-a", PROVIDER_T2, now=NOW)
        assert recovered.session_id.startswith("sess_")
    finally:
        authority.close()


def test_reclaimed_session_marker_logout_fences(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """용량 회수도 표식을 남긴다 — 뒤늦은 로그아웃이 대기 의도를 펜싱한다."""
    import ksi_core.identity.browser_session_authority as module

    monkeypatch.setattr(module, "_MAX_SESSIONS", 2)
    authority = _authority(tmp_path)
    try:
        lineage_one = _lineage(authority)
        lineage_two = _lineage(authority)
        credential_a, _ = _login(authority, lineage_one, "operator-a", "org-a", refresh=PROVIDER_T0)
        _login(authority, lineage_two, "operator-b", "org-a", refresh=PROVIDER_T1)
        late = NOW + SESSION_TTL + timedelta(seconds=1)
        pending = _begin(authority, lineage_one, now=late)
        lineage_three = _lineage(authority, now=late)
        nonce_c = _begin(authority, lineage_three, now=late)
        credential_c = authority.complete_login(
            nonce_c, "operator-c", "org-a", PROVIDER_T2, now=late
        )
        assert credential_c.session_id.startswith("sess_")
        assert authority.counts().sessions == 1
        # 회수로 만료된 A 의 로그아웃이 허가되고 대기 의도를 펜싱한다.
        authority.logout(credential_a.session_id, credential_a.session_secret, now=late)
        with pytest.raises(SessionAuthError):
            authority.complete_login(pending, "operator-a", "org-a", PROVIDER_T1, now=late)
        # 표식은 소진됐다.
        with pytest.raises(SessionAuthError):
            authority.logout(credential_a.session_id, credential_a.session_secret, now=late)
        credential_next, _ = _login(authority, lineage_one, refresh=PROVIDER_T1, now=late)
        assert credential_next.session_id.startswith("sess_")
    finally:
        authority.close()


def test_revocation_cap_seals_instead_of_evicting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """파기 기록이 살아있는 표식으로 가득 차면 전체를 봉인하고 거부한다 —
    표식을 버리지도 세션을 죽이지도 않는다."""
    import ksi_core.identity.browser_session_authority as module

    monkeypatch.setattr(module, "_MAX_REVOCATIONS", 3)
    authority = _authority(tmp_path)
    try:
        lineages = [_lineage(authority) for _ in range(3)]
        for lineage in lineages:
            credential, _ = _login(authority, lineage, refresh=PROVIDER_T0)
            authority.begin_refresh(credential.session_id, credential.session_secret, now=NOW)
            late = NOW + RESERVATION_TTL + timedelta(seconds=1)
            with pytest.raises(SessionAuthError):
                authority.authenticate(credential.session_id, credential.session_secret, now=late)
        assert authority.counts().revocations == 3
        assert authority.counts().sessions == 0
        lineage_new = _lineage(authority)
        credential_new, _ = _login(authority, lineage_new, refresh=PROVIDER_T1)
        authority.begin_refresh(credential_new.session_id, credential_new.session_secret, now=NOW)
        late = NOW + RESERVATION_TTL + timedelta(seconds=1)
        # 살아있는 표식만 가득 찼다 — 전체를 봉인하고 거부한다(인증 실패가 아니다).
        with pytest.raises(SessionRecoveryError, match="상한 초과"):
            authority.authenticate(
                credential_new.session_id, credential_new.session_secret, now=late
            )
        # 봉인 뒤에는 어떤 동작도 거부된다 — 조용한 부분 적용이 없다.
        with pytest.raises(SessionRecoveryError):
            authority.counts()
    finally:
        authority.close()


def test_ordinary_tombstones_evict_before_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """일반 파기 기록은 표식을 위해 치워진다 — 살아있는 표식은 남는다."""
    import ksi_core.identity.browser_session_authority as module

    monkeypatch.setattr(module, "_MAX_REVOCATIONS", 2)
    authority = _authority(tmp_path)
    try:
        lineage_a = _lineage(authority)
        credential_a, _ = _login(authority, lineage_a, refresh=PROVIDER_T0)
        authority.logout(credential_a.session_id, credential_a.session_secret, now=NOW)
        lineage_b = _lineage(authority)
        credential_b, _ = _login(authority, lineage_b, refresh=PROVIDER_T0)
        authority.begin_refresh(credential_b.session_id, credential_b.session_secret, now=NOW)
        late = NOW + RESERVATION_TTL + timedelta(seconds=1)
        with pytest.raises(SessionAuthError):
            authority.authenticate(credential_b.session_id, credential_b.session_secret, now=late)
        assert authority.counts().revocations == 2
        lineage_c = _lineage(authority)
        credential_c, _ = _login(authority, lineage_c, refresh=PROVIDER_T1)
        authority.begin_refresh(credential_c.session_id, credential_c.session_secret, now=NOW)
        # 일반 묘비가 치워지고 표식이 들어간다 — 세션은 닫힌다.
        with pytest.raises(SessionAuthError):
            authority.authenticate(credential_c.session_id, credential_c.session_secret, now=late)
        assert authority.counts().revocations == 2
        # 치워진 일반 묘비의 로그아웃은 거부된다.
        with pytest.raises(SessionAuthError):
            authority.logout(credential_a.session_id, credential_a.session_secret, now=late)
        # 살아있는 두 표식의 로그아웃은 모두 허가된다.
        authority.logout(credential_b.session_id, credential_b.session_secret, now=late)
        authority.logout(credential_c.session_id, credential_c.session_secret, now=late)
    finally:
        authority.close()


def test_restart_preserves_markers_over_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """재기동은 상한을 넘더라도 살아있는 표식을 버리지 않는다."""
    import ksi_core.identity.browser_session_authority as module

    monkeypatch.setattr(module, "_MAX_REVOCATIONS", 2)
    seal_key = generate_seal_key()
    authority = _authority(tmp_path, seal_key=seal_key)
    try:
        for _ in range(2):
            lineage = _lineage(authority)
            credential, _ = _login(authority, lineage, refresh=PROVIDER_T0)
            authority.begin_refresh(credential.session_id, credential.session_secret, now=NOW)
            late = NOW + RESERVATION_TTL + timedelta(seconds=1)
            with pytest.raises(SessionAuthError):
                authority.authenticate(credential.session_id, credential.session_secret, now=late)
        assert authority.counts().revocations == 2
        lineage_pending = _lineage(authority)
        credential_pending, _ = _login(authority, lineage_pending, refresh=PROVIDER_T1)
        authority.begin_refresh(
            credential_pending.session_id, credential_pending.session_secret, now=NOW
        )
    finally:
        authority.close()
    reopened = _authority(tmp_path, seal_key=seal_key)
    try:
        assert reopened.counts().sessions == 0
        # 상한을 넘겨도 표식은 모두 살아있다.
        assert reopened.counts().revocations == 3
        with pytest.raises(SessionAuthError):
            reopened.authenticate(
                credential_pending.session_id,
                credential_pending.session_secret,
                now=NOW,
            )
        # 넘친 표식도 로그아웃 펜싱에 쓸 수 있다.
        reopened.logout(credential_pending.session_id, credential_pending.session_secret, now=NOW)
    finally:
        reopened.close()


def test_two_consecutive_reopens_at_marker_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """표식으로 가득 찬 상한에서도 재기동은 두 번 연속 열린다 — 살아있는
    표식을 버리지 않고, 두 번째 재기동도 거부하지 않는다."""
    import ksi_core.identity.browser_session_authority as module

    monkeypatch.setattr(module, "_MAX_REVOCATIONS", 2)
    seal_key = generate_seal_key()
    authority = _authority(tmp_path, seal_key=seal_key)
    try:
        credentials = []
        for token in (PROVIDER_T0, PROVIDER_T1):
            lineage = _lineage(authority)
            credential, _ = _login(authority, lineage, refresh=token)
            credentials.append(credential)
            authority.begin_refresh(credential.session_id, credential.session_secret, now=NOW)
            late = NOW + RESERVATION_TTL + timedelta(seconds=1)
            with pytest.raises(SessionAuthError):
                authority.authenticate(credential.session_id, credential.session_secret, now=late)
        first_credential = credentials[0]
        assert authority.counts().revocations == 2
        lineage_pending = _lineage(authority)
        credential_pending, _ = _login(authority, lineage_pending, refresh=PROVIDER_T2)
        authority.begin_refresh(
            credential_pending.session_id, credential_pending.session_secret, now=NOW
        )
        # 닫기 전에는 그대로 둔다 — 재시작이 정리한다.
    finally:
        authority.close()
    reopened = _authority(tmp_path, seal_key=seal_key)
    try:
        assert reopened.counts().sessions == 0
        # 상한을 넘겨도 살아있는 표식은 모두 살아있다.
        assert reopened.counts().revocations == 3
        # 넘친 표식도 로그아웃 펜싱에 쓸 수 있다.
        reopened.logout(credential_pending.session_id, credential_pending.session_secret, now=NOW)
    finally:
        reopened.close()
    reopened_again = _authority(tmp_path, seal_key=seal_key)
    try:
        assert reopened_again.counts().sessions == 0
        # 격하된 일반 파기 기록은 상한 때문에 치워졌지만, 살아있는 표식은 남았다.
        assert reopened_again.counts().revocations == 2
        reopened_again.logout(first_credential.session_id, first_credential.session_secret, now=NOW)
    finally:
        reopened_again.close()


def _touch_mtime(path: Path, *, days: int) -> None:
    """mtime 위조 — chmod 없이 utime 으로만 시각을 바꾼다."""
    import time as _time

    forged = _time.time() + days * 86400
    os.utime(path, (forged, forged))


def test_forged_mtime_cannot_affect_replay(tmp_path: Path) -> None:
    """위조된 mtime(과거·미래)은 재기동에 영향을 주지 않는다 — 살아있는
    표식은 미래 mtime 에도 치워지지 않고, 세션은 그대로 복원된다."""
    for delta_days in (-30, 30):
        seal_key = generate_seal_key()
        state = tmp_path / f"store-{delta_days}.json"
        authority = _open(tmp_path, seal_key=seal_key, name=state.name)
        try:
            lineage = _lineage(authority)
            credential, _ = _login(authority, lineage, refresh=PROVIDER_T0)
            authority.begin_refresh(credential.session_id, credential.session_secret, now=NOW)
            late = NOW + RESERVATION_TTL + timedelta(seconds=1)
            with pytest.raises(SessionAuthError):
                authority.authenticate(credential.session_id, credential.session_secret, now=late)
            assert authority.counts().revocations == 1
        finally:
            authority.close()
        _touch_mtime(state, days=delta_days)
        reopened = _open(tmp_path, seal_key=seal_key, name=state.name)
        try:
            assert reopened.counts().sessions == 0
            assert reopened.counts().revocations == 1
            # 무효화된 세션은 mtime 과 무관하게 죽은 채로 남는다.
            with pytest.raises(SessionAuthError):
                reopened.authenticate(credential.session_id, credential.session_secret, now=late)
        finally:
            reopened.close()


def test_old_session_fresh_intent_pending_restart_logout(tmp_path: Path) -> None:
    """오래된 세션·새 의도·미완료 예약 뒤 재기동 — 복구 시각 기준으로
    파기·펜싱하고, 위조 mtime 과 무관하게 동작한다."""
    seal_key = generate_seal_key()
    authority = _authority(tmp_path, seal_key=seal_key)
    try:
        lineage_a = _lineage(authority)
        credential_a, _ = _login(authority, lineage_a, refresh=PROVIDER_T0)
        # 오래된 예약(완료 없이 방치)을 남긴다 — 재기동이 무효로 닫는다.
        authority.begin_refresh(credential_a.session_id, credential_a.session_secret, now=NOW)
        lineage_b = _lineage(authority)
        credential_b, _ = _login(authority, lineage_b, refresh=PROVIDER_T1)
        authority.begin_refresh(credential_b.session_id, credential_b.session_secret, now=NOW)
        state = tmp_path / "browser-sessions.json"
    finally:
        authority.close()
    _touch_mtime(state, days=-30)
    recovered_at = NOW + timedelta(days=9)
    reopened = _open(tmp_path, seal_key=seal_key, now=recovered_at)
    try:
        # 두 세션 모두 미완료 예약 탓에 무효가 됐다.
        assert reopened.counts().sessions == 0
        assert reopened.counts().revocations == 2
        # 새 의도는 살아있다 — 복구 뒤 로그아웃이 펜싱한다.
        fresh_a = reopened.begin_login(
            lineage_a.lineage_id, lineage_a.lineage_secret, now=recovered_at
        )
        reopened.logout(credential_a.session_id, credential_a.session_secret, now=recovered_at)
        with pytest.raises(SessionAuthError):
            reopened.complete_login(fresh_a, "operator-a", "org-a", PROVIDER_T2, now=recovered_at)
        # 파기 시각이 복구 시각 기준이므로 보존 기한 안에 로그아웃이 허가된다.
        # (세션 생성 시각 기준이었다면 이미 만료돼 거부된다.)
        late = recovered_at + timedelta(days=6)
        reopened.logout(credential_b.session_id, credential_b.session_secret, now=late)
        with pytest.raises(SessionAuthError):
            reopened.logout(credential_b.session_id, credential_b.session_secret, now=late)
    finally:
        reopened.close()


def test_symlink_alias_to_valid_store_is_refused(tmp_path: Path) -> None:
    """실제 유효 저장소를 가리키는 심볼릭 링크로는 열 수 없다 —
    resolve 가 링크를 삼키기 전에 거부해야 한다."""
    seal_key = generate_seal_key()
    authority = _open(tmp_path, seal_key=seal_key, name="real.json")
    try:
        lineage = _lineage(authority)
        credential, _ = _login(authority, lineage, refresh=PROVIDER_T0)
        assert credential.session_id.startswith("sess_")
    finally:
        authority.close()
    alias = tmp_path / "alias.json"
    os.symlink(tmp_path / "real.json", alias)
    with pytest.raises(SessionRecoveryError):
        _open(tmp_path, seal_key=seal_key, name="alias.json")


def test_symlink_ancestor_to_valid_store_is_refused(tmp_path: Path) -> None:
    """A valid encrypted store cannot be opened through a symlinked parent."""
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    key = generate_seal_key()
    authority = _open(private, seal_key=key)
    authority.close()
    alias = tmp_path / "alias-dir"
    alias.symlink_to(private, target_is_directory=True)
    with pytest.raises(SessionRecoveryError):
        _open(alias, seal_key=key)


def test_symlink_lock_path_is_refused(tmp_path: Path) -> None:
    """잠금 경로의 심볼릭 링크는 따라가지 않고 거부한다."""
    seal_key = generate_seal_key()
    authority = _open(tmp_path, seal_key=seal_key, name="real.json")
    try:
        lineage = _lineage(authority)
        _login(authority, lineage, refresh=PROVIDER_T0)
    finally:
        authority.close()
    lock_path = tmp_path / "real.json.lock"
    assert lock_path.exists()
    os.unlink(lock_path)
    os.symlink(tmp_path / "real.json", lock_path)
    with pytest.raises(SessionRecoveryError):
        _open(tmp_path, seal_key=seal_key, name="real.json")


def test_fifo_lock_path_is_refused(tmp_path: Path) -> None:
    """잠금 경로는 일반 파일만 허용한다 — 특수 파일을 열지 않는다."""
    seal_key = generate_seal_key()
    authority = _open(tmp_path, seal_key=seal_key, name="real.json")
    try:
        lineage = _lineage(authority)
        _login(authority, lineage, refresh=PROVIDER_T0)
    finally:
        authority.close()
    lock_path = tmp_path / "real.json.lock"
    os.unlink(lock_path)
    os.mkfifo(lock_path)
    with pytest.raises(SessionRecoveryError):
        _open(tmp_path, seal_key=seal_key, name="real.json")


def test_dangling_state_symlink_is_not_initialized(tmp_path: Path) -> None:
    state = tmp_path / "browser-sessions.json"
    state.symlink_to(tmp_path / "missing-target")
    with pytest.raises(SessionRecoveryError):
        _authority(tmp_path)
    assert state.is_symlink()
    assert not (tmp_path / "missing-target").exists()


def test_leftover_temporary_file_requires_recovery(tmp_path: Path) -> None:
    key = generate_seal_key()
    authority = _authority(tmp_path, seal_key=key)
    authority.close()
    leftover = tmp_path / "browser-sessions.json.tmp"
    leftover.write_bytes(b"synthetic leftover")
    with pytest.raises(SessionRecoveryError):
        _authority(tmp_path, seal_key=key)
    assert leftover.read_bytes() == b"synthetic leftover"
