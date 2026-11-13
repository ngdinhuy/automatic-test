"""Kiểm chứng decoder bằng video thật và parser không nhận log cũ/UID khác thành số đo."""
import importlib.util
import subprocess
from pathlib import Path

import pytest

from tammi_runner.common import ROOT,Blocked
from tammi_runner.video import binary,decode
from tammi_runner.android_signals import players,vibrations,after_snapshot


@pytest.fixture
def probe(monkeypatch):
    directory=ROOT/'scripts/probes';monkeypatch.syspath_prepend(str(directory))
    spec=importlib.util.spec_from_file_location('test_video_integrity',directory/'video_integrity.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def make_video(path,color='testsrc2=size=96x64:rate=10',seconds=2,audio=True):
    args=[binary(),'-v','error','-f','lavfi','-i',color]
    if audio:args+=['-f','lavfi','-i',f'sine=frequency=900:duration={seconds}']
    args+=['-t',str(seconds),'-c:v','mpeg4','-q:v','2']
    if audio:args+=['-c:a','aac']
    subprocess.run(args+['-movflags','+faststart','-y',str(path)],capture_output=True,check=True)
    return path


def test_video_decodes_all_frames_and_compares_identical_file(tmp_path,probe):
    source=make_video(tmp_path/'source.mp4')
    result=probe.compare(source,source,tmp_path)
    assert result['source']['frames']==20
    assert result['source']['has_audio'] and result['checksum_matches']==1
    assert len(result['samples'])==5 and result['duration_error_seconds']==0


def test_invalid_video_cannot_pass_by_extension(tmp_path):
    path=tmp_path/'fake.mp4';path.write_bytes(b'not a video')
    with pytest.raises(AssertionError,match='giải mã'):decode(path)


def test_truncated_media_fails_even_with_metadata_at_start(tmp_path):
    path=make_video(tmp_path/'truncated.mp4')
    data=path.read_bytes();path.write_bytes(data[:len(data)*3//4])
    with pytest.raises(AssertionError,match='giải mã'):decode(path)


def test_valid_but_different_video_fails_content_comparison(tmp_path,probe):
    source=make_video(tmp_path/'source.mp4')
    wrong=make_video(tmp_path/'wrong.mp4','color=c=red:size=96x64:rate=10')
    with pytest.raises(AssertionError,match='Frame video'):probe.compare(source,wrong,tmp_path)


def test_cut_video_fails_duration_comparison(tmp_path,probe):
    source=make_video(tmp_path/'source.mp4',seconds=3)
    short=make_video(tmp_path/'short.mp4',seconds=1)
    with pytest.raises(AssertionError,match='thời lượng'):probe.compare(source,short,tmp_path)


def test_missing_audio_track_fails_comparison(tmp_path,probe):
    source=make_video(tmp_path/'source.mp4')
    silent=make_video(tmp_path/'silent.mp4',audio=False)
    with pytest.raises(AssertionError,match='mất track audio'):probe.compare(source,silent,tmp_path)


def test_only_current_uid_started_players_are_counted():
    text='''AudioPlaybackConfiguration piid:1 type:android.media.MediaPlayer u/pid:11032/20 state:started attr: usage=USAGE_NOTIFICATION_RINGTONE mutedState:none
AudioPlaybackConfiguration piid:2 type:android.media.MediaPlayer u/pid:999/20 state:started attr: usage=USAGE_NOTIFICATION_RINGTONE mutedState:none
AudioPlaybackConfiguration piid:3 type:android.media.MediaPlayer u/pid:11032/20 state:stopped attr: usage=USAGE_NOTIFICATION_RINGTONE mutedState:none
11-12 10:00:00 player piid:4 event:started'''
    result=players(text,11032)
    assert len(result)==1 and result[0]['piid']=='1' and result[0]['ringtone_candidate']


def test_ignored_or_unrelated_vibrations_cannot_pass():
    prefix='11-12 10:00:00.001 | effect | '
    suffix=' | duration: 500ms | start: 10:00:00.001 | end: 10:00:00.501 | scale: NONE | flags: 0 | usage: RINGTONE | '
    text='\n'.join([prefix+'finished'+suffix+'com.example.app (uid=11032, deviceId=0)',
                    prefix.replace('.001','.002')+'ignored_unsupported'+suffix+'com.example.app (uid=11032, deviceId=0)',
                    prefix.replace('.001','.003')+'finished'+suffix+'com.other (uid=999, deviceId=0)'])
    result=vibrations(text,'com.example.app',11032)
    assert len(result)==2 and sum(row['accepted'] for row in result.values())==1


def test_system_notification_vibration_must_identify_target_package_and_uid():
    line='11-12 10:00:00.001 | effect | finished | duration: 500ms | start: 10:00:00.001 | end: 10:00:00.501 | scale: NONE | flags: 0 | usage: NOTIFICATION | android (uid=1000, deviceId=0) | reason: Notification (com.example.app 11032)'
    assert len(vibrations(line,'com.example.app',11032))==1
    assert not vibrations(line,'com.example.app',1103)


def test_finished_old_vibration_is_not_new_and_year_boundary_is_supported():
    assert not after_snapshot('11-12 09:59:59.900','2026-11-12T10:00:00+0700')
    assert after_snapshot('11-12 10:00:00.100','2026-11-12T10:00:00+0700')
    assert after_snapshot('01-01 00:00:01.000','2026-12-31T23:59:59+0700')
    assert not after_snapshot('12-31 23:59:58.000','2027-01-01T00:00:00+0700')
