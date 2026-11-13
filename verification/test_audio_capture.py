"""Kiểm tra đối chiếu âm và quyền sở hữu phiên thu, không tính PASS testcase app."""
import random
from unittest.mock import patch
import pytest
from tammi_runner.audio_analysis import rms,similarity
from tammi_runner.audio_capture import begin,stop
from tammi_runner.common import Blocked


def test_reference_survives_delay_gain_offset_and_noise():
    rng=random.Random(17)
    reference=[rng.randint(-12000,12000) for _ in range(1000)]
    record=[0]*127+[int(x*.4)+800+rng.randint(-100,100) for x in reference]+[0]*200
    assert similarity(record,reference)>.99
    assert rms(record)>0
    assert similarity([0]*1500,reference)==0
    assert similarity([rng.randint(-10000,10000) for _ in range(1500)],reference)<.2
    with pytest.raises(ValueError):similarity([1],reference)


def test_never_stop_or_overwrite_another_recording():
    with patch('tammi_runner.audio_capture.state',return_value={'active':True,'marker':'other'}),patch('tammi_runner.audio_capture.adb') as command:
        with pytest.raises(Blocked):begin({},'C','owned')
        with pytest.raises(Blocked):stop({},'C','owned')
        command.assert_not_called()
