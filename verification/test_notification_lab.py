from tammi_runner.notification_lab import containers


def source(bounds='[15,79][705,234]',peer='HuyVT'):
    return f'<hierarchy><node class="android.view.View" clickable="true" long-clickable="true" bounds="{bounds}"><node class="android.widget.TextView" text="{peer}"/><node class="android.widget.TextView" text="APPIUM-test"/></node></hierarchy>'


def test_overlay_detected_but_message_bubble_not_used_as_banner():
    assert len(containers(source(),720,1600,'HuyVT'))==1
    assert not containers(source('[15,500][600,680]'),720,1600,'HuyVT')
    assert not containers(source('[15,79][550,234]'),720,1600,'HuyVT')
    assert not containers(source(peer='Other'),720,1600,'HuyVT')
