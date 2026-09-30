import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
for (const scenario of ['loop','silence','noise','max_recording','late_permission','late_stt','switch','disconnect',
  'hidden','denied','no_speech','voice_end','tts_failure','interrupt_work','interrupt_tts','pause_pending',
  'saved_audio','duplicate','draft','device_loss','new_conversation','other_task','resume_permission_pending','resume_work_pending',
  'audio_after_microphone','permission_timeout','audio_timeout','pause_preparing','background_result',
  'approval_denied','approval_timeout','approval_stop',
  'barge_settled','barge_wait','barge_timeout','barge_pause','barge_off','barge_unavailable',
  'barge_late_setup','barge_toggle','barge_no_speech','barge_late_ended','barge_saved_audio',
  'barge_disconnect','barge_hidden','barge_switch','barge_error','barge_helper_closed','barge_empty','barge_stt_failure']) {
  test(`Talk audio lifecycle: ${scenario}`, () => {
    const env = {...process.env};
    delete env.NODE_TEST_CONTEXT;
    const result = spawnSync(process.execPath, [new URL('./talk-harness.cjs', import.meta.url).pathname, scenario], {env, encoding:'utf8', timeout:10000});
    assert.ifError(result.error);
    assert.equal(result.status, 0, result.stdout + result.stderr);
    assert.match(result.stdout, /passed/);
  });
}
