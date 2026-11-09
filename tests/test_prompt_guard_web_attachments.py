"""Attachment evidence is screened before live or historical model insertion."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest
from test_web_attachment_bundle_chat import image, note
from test_web_attachment_bundle_chat import journey as journey

from lib import prompt_guard as guard
from lib import prompt_guard_incidents as incidents
from lib import prompt_guard_observer as observer
from lib.prompt_guard import PromptGuardResult

PAYLOAD = "Synthetic external attachment evidence with a planted directive."


@pytest.fixture
def scans(monkeypatch, tmp_path):
    assert incidents.get_project_root() == tmp_path
    calls = []
    verdict = {"status": "scanned", "flagged": True}
    monkeypatch.setattr(guard, "is_enabled", lambda: True)
    monkeypatch.setattr(observer, "is_enabled", lambda: True)
    monkeypatch.setattr(observer, "notify_prompt_guard_block", lambda *_args, **_kwargs: None)

    def scan(text, **kwargs):
        calls.append((text, kwargs))
        return PromptGuardResult(
            **verdict, injection_score=0.99, threshold=0.8,
            coverage_complete=True, windows_scanned=1, input_bytes=len(text.encode()),
        )

    monkeypatch.setattr(observer, "scan_text", scan)
    return calls, verdict


def response(journey):
    return next(payload for event, payload, _options in reversed(journey.socket.events)
                if event == "chat:response")


def test_current_attachment_block_never_constructs_or_calls_model(journey, scans):
    source = note(PAYLOAD)
    journey.send(attachments=[source])
    journey.process()

    assert not journey.instances and not journey.routes
    reply = response(journey)
    assert reply["ok"] is False and reply["run_status"] == "failed"
    assert reply["data"]["prompt_guard"]["content_withheld"] is True
    receipt = reply["data"]["prompt_guard"]
    assert receipt["evidence_saved"] is True
    incident_path = next((journey.tmp / 'logs/prompt-guard/incidents/cloud').glob(
        f'*{receipt["incident_id"]}.json',
    ))
    incident = json.loads(incident_path.read_text())
    assert incident_path.name == f'{incident["created_at"][:10]}-{receipt["incident_id"]}.json'
    assert incident['source_type'] == 'attachment'
    assert incident['evidence']['text'] == PAYLOAD
    assert reply["data"]["operation"]["tool_executed"] is False
    assert not reply["completion_guard"]["prompt_user"]
    assert PAYLOAD not in str(reply)
    saved = journey.store.get_conversation(reply["conversation_id"])["messages"][-1]
    assert saved["data"]["prompt_guard"]["content_withheld"] is True
    assert saved["data"]["_run_status"] == "failed"
    assert PAYLOAD not in str(saved)
    record = journey.handler._get_completion_guard_record("client", reply["message_id"])
    assert record["prompt_guard_blocked"] is True
    assert record["processed_query"] == "Compare these sources."
    assert scans[0][0][0] == PAYLOAD


def test_marker_write_failure_cannot_replace_current_attachment_rejection(journey, scans, monkeypatch, capsys):
    def fail(*_args):
        raise OSError('SECRET-STORAGE-ERROR')

    monkeypatch.setattr(journey.store, 'withhold_text_attachment', fail)
    journey.send(attachments=[note(PAYLOAD)])
    journey.process()
    reply = response(journey)
    assert reply['ok'] is False and reply['data']['prompt_guard']['content_withheld'] is True
    assert not journey.instances and not journey.routes
    assert PAYLOAD not in str(reply)
    assert 'SECRET-STORAGE-ERROR' not in capsys.readouterr().out


def test_historical_block_omits_evidence_without_stopping_vision_or_new_turn(journey, scans, monkeypatch):
    calls, verdict = scans
    verdict["flagged"] = False
    journey.send(attachments=[note(PAYLOAD)])
    journey.process()
    conversation_id = response(journey)["conversation_id"]
    before = len(journey.routes)
    verdict["flagged"] = True
    calls.clear()

    prepared = []

    def prepare(**kwargs):
        assert calls and calls[0][0] == PAYLOAD
        assert PAYLOAD not in kwargs['message']
        prepared.append(True)
        return kwargs['message'], None, {}, {}, []

    monkeypatch.setattr(journey.handler, "_prepare_uploaded_images", prepare)
    journey.send(message="Compare the new image.", conversation_id=conversation_id, image=image())
    journey.process()

    assert prepared == [True] and len(journey.routes) == before + 1
    assert response(journey)["ok"] is True
    context = journey.routes[-1][1]['conversation_history'][0]['attachment_context']
    assert PAYLOAD not in context
    assert 'Source 1 text was withheld by Prompt Guard' in context
    assert 'automatically retrieve it again' in context
    assert calls[0][0] == PAYLOAD


def test_rejected_upload_does_not_lock_out_or_reenter_later_messages(journey, scans):
    source = note(PAYLOAD)
    journey.send(attachments=[source])
    journey.process()
    conversation_id = response(journey)['conversation_id']
    assert response(journey)['ok'] is False
    restored = type(journey.store)(journey.tmp / 'conversations').get_conversation(conversation_id)
    assert restored['prompt_guard_withheld_text'] == {source['stash_ref']: source['sha256']}
    scans[1].update(status='unknown', flagged=None)
    scans[0].clear()

    for message in ('What time is it?', 'Now explain how reminders work.'):
        journey.send(message=message, conversation_id=conversation_id)
        journey.process()
        assert response(journey)['ok'] is True
        prompt, kwargs = journey.routes[-1]
        assert message in prompt
        assert PAYLOAD not in str((prompt, kwargs))
        assert kwargs['conversation_history'][0]['content'] == 'Compare these sources.'
        assert 'withheld by Prompt Guard' in kwargs['conversation_history'][0]['attachment_context']

    assert len(journey.routes) == 2
    assert not scans[0]  # A later outage cannot reinsert already rejected source text.
    assert (journey.tmp / 'stash' / source['space_id'] / source['filename']).read_text() == PAYLOAD


def test_history_block_omits_only_flagged_source(journey, scans, monkeypatch):
    safe = 'A clean source with ordinary evidence.'
    scans[1]['flagged'] = False
    journey.send(attachments=[note(PAYLOAD), note(safe, name='clean.txt')])
    journey.process()
    conversation_id = response(journey)['conversation_id']
    original = observer.scan_text

    def selective(text, **kwargs):
        scans[1]['flagged'] = text == PAYLOAD
        return original(text, **kwargs)

    monkeypatch.setattr(observer, 'scan_text', selective)
    journey.send(message='Summarize the clean source.', conversation_id=conversation_id)
    journey.process()
    assert response(journey)['ok'] is True
    context = journey.routes[-1][1]['conversation_history'][0]['attachment_context']
    assert PAYLOAD not in context and safe in context
    assert 'Source 1 text was withheld by Prompt Guard' in context
    assert '[TEXT CONTENT — Source 2:' in context
    scans[1].update(status='unknown', flagged=None)
    scans[0].clear()
    journey.send(message='Continue with the clean source.', conversation_id=conversation_id)
    journey.process()
    assert response(journey)['ok'] is True
    context = journey.routes[-1][1]['conversation_history'][0]['attachment_context']
    assert PAYLOAD not in context and safe in context
    assert [text for text, _kwargs in scans[0]] == [safe]


@pytest.mark.parametrize('marker_write_fails', [False, True])
def test_repeated_historical_ref_cannot_reenter_same_turn_after_first_block(
    journey, scans, monkeypatch, marker_write_fails,
):
    source = note(PAYLOAD)
    scans[1]['flagged'] = False
    journey.send(attachments=[source])
    journey.process()
    conversation_id = response(journey)['conversation_id']
    journey.send(attachments=[source], conversation_id=conversation_id)
    journey.process()
    scans[0].clear()
    scans[1].update(status='scanned', flagged=True)
    original = observer.scan_text

    def first_block_then_unknown(text, **kwargs):
        result = original(text, **kwargs)
        scans[1].update(status='unknown', flagged=None)
        return result

    monkeypatch.setattr(observer, 'scan_text', first_block_then_unknown)
    if marker_write_fails:
        def fail(*_args):
            raise OSError('Synthetic marker failure')
        monkeypatch.setattr(journey.store, 'withhold_text_attachment', fail)
    journey.send(message='Continue without that evidence.', conversation_id=conversation_id)
    journey.process()

    assert response(journey)['ok'] is True
    assert len(scans[0]) == 1
    history = journey.routes[-1][1]['conversation_history']
    assert PAYLOAD not in str(history)
    contexts = [entry['attachment_context'] for entry in history if entry.get('attachment_context')]
    assert len(contexts) == 2
    assert all('text was withheld by Prompt Guard' in context for context in contexts)


@pytest.mark.parametrize("status,flagged", [("scanned", False), ("unknown", None), ("skipped", None)])
def test_clean_or_unscanned_text_keeps_existing_attachment_flow(journey, scans, status, flagged):
    calls, verdict = scans
    verdict.update(status=status, flagged=flagged)
    source = note(PAYLOAD)
    before = deepcopy(source)
    journey.send(attachments=[source])
    journey.process()

    assert response(journey)["ok"] is True
    assert PAYLOAD in journey.routes[0][0]
    assert source == before
    assert calls[0][1] == {"source_type": "attachment", "source_name": "web_text"}


@pytest.mark.parametrize('text,budget,expected', [
    ('a' * 9000 + 'OMITTED_TAIL', 8192, 'a' * 8192),
    ('a' * 8191 + '😀OMITTED_TAIL', 8192, 'a' * 8191),
    ('😀' * 3000 + 'OMITTED_TAIL', 8192, '😀' * 2048),
    ('😀OMITTED_TAIL', 1, ''),
    ('a' * 102400, 262144, 'a' * 102400),
])
def test_web_inserts_exact_scannable_utf8_excerpt_and_preserves_full_file(
    journey, scans, monkeypatch, text, budget, expected,
):
    monkeypatch.setenv('JARVIS_OVERRIDE_PROMPT_GUARD_MAX_INPUT_BYTES', str(budget))
    scans[1]['flagged'] = False
    source = note(text)
    journey.send(attachments=[source])
    journey.process()

    assert response(journey)['ok'] is True
    prompt = journey.routes[0][0]
    assert len(expected.encode('utf-8')) <= budget
    if expected:
        assert scans[0][0][0] == expected
    else:
        assert not scans[0]  # No character fits; metadata and an excerpt notice remain.
    omitted = len(expected) < len(text)
    assert ('[Excerpt only;' in prompt) is omitted
    assert f']\n{expected}' in prompt
    assert 'OMITTED_TAIL' not in prompt
    assert source['stash_ref'] in prompt
    assert (journey.tmp / 'stash' / source['space_id'] / source['filename']).read_text() == text


def test_unicode_history_is_bounded_by_bytes_not_only_characters(journey, scans, monkeypatch):
    scans[1]['flagged'] = False
    monkeypatch.setenv('JARVIS_OVERRIDE_PROMPT_GUARD_MAX_INPUT_BYTES', '262144')
    text = '😀' * 5000 + 'OMITTED_TAIL'
    journey.send(attachments=[note(text)])
    journey.process()
    conversation_id = response(journey)['conversation_id']
    monkeypatch.setenv('JARVIS_OVERRIDE_PROMPT_GUARD_MAX_INPUT_BYTES', '8192')
    scans[0].clear()
    journey.send(message='Continue with the excerpt.', conversation_id=conversation_id)
    journey.process()

    assert scans[0][0][0] == '😀' * 2048
    context = journey.routes[-1][1]['conversation_history'][0]['attachment_context']
    assert '😀' * 2048 in context and '😀' * 2049 not in context
    assert 'OMITTED_TAIL' not in context and '[Excerpt only;' in context


@pytest.mark.parametrize('status,flagged', [('unknown', None), ('skipped', None)])
def test_unavailable_scan_keeps_fail_open_for_only_the_bounded_excerpt(
    journey, scans, monkeypatch, status, flagged,
):
    monkeypatch.setenv('JARVIS_OVERRIDE_PROMPT_GUARD_MAX_INPUT_BYTES', '8192')
    scans[1].update(status=status, flagged=flagged)
    journey.send(attachments=[note('a' * 9000 + 'OMITTED_TAIL')])
    journey.process()
    assert response(journey)['ok'] is True
    assert scans[0][0][0] == 'a' * 8192
    prompt = journey.routes[0][0]
    assert 'a' * 8192 in prompt and 'OMITTED_TAIL' not in prompt
    assert '[Excerpt only;' in prompt


def test_legacy_direct_text_context_is_screened_without_scanning_user_request(journey, scans):
    conversation_id = journey.store.create_conversation()["id"]
    journey.handler._process_message(
        "client", "Authorized task instructions", "cloud", "legacy-message", conversation_id,
        file_context={"name": "fixture.txt", "content": PAYLOAD},
    )

    assert not journey.instances and not journey.routes
    assert scans[0][0][0] == PAYLOAD
    assert response(journey)["ok"] is False


def test_legacy_direct_text_uses_byte_budget_and_labels_omission(journey, scans, monkeypatch):
    monkeypatch.setenv('JARVIS_OVERRIDE_PROMPT_GUARD_MAX_INPUT_BYTES', '8192')
    scans[1]['flagged'] = False
    conversation_id = journey.store.create_conversation()['id']
    journey.handler._process_message(
        'client', 'Authorized task instructions', 'cloud', 'legacy-message', conversation_id,
        file_context={'name': 'fixture.txt', 'content': '😀' * 3000 + 'OMITTED_TAIL'},
    )
    assert response(journey)['ok'] is True
    assert scans[0][0][0] == '😀' * 2048
    prompt = journey.routes[0][0]
    assert '😀' * 2048 in prompt and '😀' * 2049 not in prompt
    assert 'OMITTED_TAIL' not in prompt
    assert '[Excerpt only; the remaining attached text was not inserted.]' in prompt


def test_cancellation_during_attachment_scan_wins_over_block_presentation(journey, scans, monkeypatch):
    original = observer.scan_text

    def scan_and_cancel(text, **kwargs):
        run = next(iter(journey.handler.runs.active.values()))
        journey.handler.pending_cancellations[run["message_id"]] = True
        return original(text, **kwargs)

    monkeypatch.setattr(observer, "scan_text", scan_and_cancel)
    journey.send(attachments=[note(PAYLOAD)])
    journey.process()

    reply = response(journey)
    assert reply["cancelled"] is True
    assert not journey.instances and not journey.routes
    assert PAYLOAD not in str(reply)
    scans[1].update(status='unknown', flagged=None)
    scans[0].clear()
    journey.send(message='Continue without that source.', conversation_id=reply['conversation_id'])
    journey.process()
    assert response(journey)['ok'] is True
    assert not scans[0]
    assert PAYLOAD not in str(journey.routes[-1])


def test_disabled_guard_does_not_submit_attachment_text(journey, scans, monkeypatch):
    monkeypatch.setattr(guard, "is_enabled", lambda: False)
    monkeypatch.setattr(observer, "is_enabled", lambda: False)
    text = 'a' * 9000 + PAYLOAD
    journey.send(attachments=[note(text)])
    journey.process()
    assert response(journey)["ok"] is True
    assert text in journey.routes[0][0]
    assert '[Excerpt only;' not in journey.routes[0][0]
    assert all(not text for text, _source in scans[0])
