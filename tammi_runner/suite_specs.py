"""Tách từng nhóm Excel thành biến thể chức năng; không sinh case chỉ để đánh dấu đủ số lượng."""


def full_suite():
    cases = []
    def add(sheet, row, suffix, name, flow, *, roles=("A", "B"), requires=(), checks=(), **params):
        source = f"{sheet}-SRC-{row:03}"
        cases.append(dict(id=f"{sheet}-{row:03}-{suffix}", name=name, roles=roles, action="suite",
                          sources=(source,), params={"flow": flow, **params}, requirements=tuple(requires),
                          obligations=tuple(checks), coverage_level="functional",
                          note="Script chức năng. PASS yêu cầu đủ mọi assertion; chưa nghiệm thu trên thiết bị. "
                               + ("Điều kiện: " + ", ".join(requires) if requires else "")))
    add("CHAT",2,"CACHE","Tin đã tải còn đọc được khi offline","cache",checks=("received_online","cached_offline"))
    for kind in ("medium", "maximum"):
        add("CHAT",3,kind.upper(),f"Text {kind}, đúng đủ nội dung hai chiều","text",requires=("limit:text_max",) if kind=="maximum" else (),checks=("exact_payload_both_directions",),length=kind)
    add("CHAT",4,"VOICE","Ghi âm, gửi và phát lại tin thoại","voice",requires=("probe:voice_playback_signal",),
        checks=("new_voice_message","receiver_playback_signal_started","receiver_playback_signal_stopped"))
    add("CHAT",5,"MENTION","Mention đúng thành viên trong nhóm","mention",requires=("group:primary","lab:member_names"),checks=("mention_identity","received_mention"))
    for media in ("camera_photo","camera_video","multiple_images"):
        add("CHAT",6,media.upper(),f"Gửi và mở media: {media}","media",requires=("fixture:"+media,),checks=("sent_media","receiver_open","media_metadata"),media=media)
    for quality in ("standard","hd","original"):
        add("CHAT",7,quality.upper(),f"Ảnh/tệp dưới 100 MB: {quality}","media",requires=("fixture:image_under_100mb",),checks=("sent_media","receiver_open","media_metadata","compression_size"),media="image_under_100mb",quality=quality)
    for media in ("video_over_1000mb","image_over_20mb"):
        add("CHAT",8,media.upper(),f"Từ chối vượt dung lượng: {media}","media",requires=("fixture:"+media,),checks=("size_limit_error","no_delivery"),media=media,reject=True)
    add("CHAT",9,"REPLY","Reply tin có mention","reply_mention",requires=("group:primary","lab:member_names"),checks=("quoted_mention","reply_received"))
    for row, flow, name, checks in (
        (10,"forward","Chuyển tiếp tin test",("forwarded_payload",)),
        (11,"offline_send","Gửi offline, báo lỗi rồi retry khi online",("offline_error","retry_delivered_once")),
        (12,"edit","Sửa tin test và đồng bộ hai máy",("edited_both_sides","old_payload_absent")),
        (13,"delete","Thu hồi tin test ở mọi người",("deleted_both_sides",)),
        (14,"reaction","Thả, xem người thả và gỡ reaction",("reaction_added","reactor_identity","reaction_count","reaction_removed")),
        (15,"draft_send","Khôi phục nháp, gửi, bỏ trạng thái nháp",("draft_preview","draft_restored","sent","draft_badge_removed")),
        (16,"pin_message","Ghim và bỏ ghim tin test",("pinned_payload","unpinned_payload")),
        (17,"search_message","Tìm tin có marker trong hội thoại",("search_exact_payload",)),
        (18,"last_message","Last message cập nhật ở danh sách",("received","conversation_preview")),
        (19,"pin_conversation","Hội thoại ghim gần nhất đứng đầu",("pinned_order","restore_pins")),
    ):
        req=("group:primary",) if row==19 else ()
        add("CHAT",row,"FUNCTIONAL",name,flow,requires=req,checks=checks)
    for row, state in ((20,"killed_locked"),(21,"killed"),(22,"background"),(27,"sleep")):
        add("CHAT",row,state.upper(),f"Push tin khi {state}","notification",requires=("probe:notification_alert",),checks=("notification_payload","notification_alert_dispatch","open_correct_conversation"),state=state,sleep_seconds=330 if row==27 else 0)
    for variant in ("same_conversation","other_conversation"):
        add("CHAT",23,variant.upper(),f"Thông báo in-app: {variant}","inapp_notification",requires=("group:primary",) if variant=="other_conversation" else (),checks=("inapp_notification_policy",),variant=variant)
    add("CHAT",24,"POLL","Tạo bình chọn, B bỏ phiếu và A nhận kết quả","poll",requires=("group:primary",),checks=("poll_created","vote_synced"))
    for row,flow,name,checks in ((25,"notification_clear","Đọc tin từ push xóa notification",("notification_before","correct_conversation","notification_removed")),(26,"unread","Số unread hội thoại và badge",("unread_exact_count","badge_count","read_clears_count")),(28,"typing","Typing xuất hiện rồi biến mất",("typing_visible","typing_cleared")),(29,"unread_banner","Mở push thấy số tin chưa đọc",("unread_banner_exact_count","unread_banner_persists_3s"))):
        req=("probe:launcher_badge",) if row==26 else ()
        add("CHAT",row,"FUNCTIONAL",name,flow,requires=req,checks=checks)
    add("CHAT",30,"CAMERA","Chụp ảnh trong app, gửi và lưu máy","media",requires=("fixture:camera_photo",),checks=("sent_media","receiver_open","camera_saved"),media="camera_photo",save_camera=True)
    for context in ("peer","group"):
        for live in (False,True):
            add("CHAT",31,f'{context.upper()}_{"LIVE" if live else "CURRENT"}',f"Chia sẻ vị trí {context}, live={live}","location",requires=(("group:primary",) if context=="group" else ())+("lab:location",),checks=("location_received","coordinates_match")+(("live_updates","live_stopped") if live else ()),context=context,live=live)
    add("CHAT",32,"RICH_TEXT","Rich text/Markdown giữ nội dung và mở link","rich_text",requires=("fixture:rich_text",),checks=("semantic_content","link_target"))
    for context in ("peer","group"):
        add("CHAT",33,context.upper(),f"Profile {context}: tìm tin, ghim, mute, media","profile",requires=("group:primary",) if context=="group" else (),checks=("profile_identity","profile_search","pin_toggle","mute_toggle","media_access"),context=context)
    add("CHAT",34,"WHATSAPP_CAMERA","Camera nhóm khi đang gọi WhatsApp","whatsapp_camera",requires=("group:primary","probe:whatsapp_call","fixture:camera_photo"),checks=("whatsapp_call_active","camera_capture","camera_not_frozen"))
    for join in ("link","qr"):
        add("CHAT",35,join.upper(),f"Tạo nhóm, chia sẻ QR/link, join bằng {join}, rời","group_lifecycle",checks=("group_created","invite_shared","joined_membership","left_membership"),join=join)
    for context in ("peer","group"):
        add("CHAT",36,context.upper(),f"@Tammi trả lời trong {context}","tammi",requires=("group:primary",) if context=="group" else (),checks=("tammi_mention","tammi_response"),context=context)
    add("CHAT",37,"ZERO_DATA","SIM hết data: Chat, Call, Meet, Viettel++","zero_data",requires=("probe:zero_data_sim","lab:zero_data_sim","group:primary","probe:meeting_media"),checks=("sim_no_quota","chat_delivered","call_connected","meeting_connected","miniapp_loaded"))
    add("CALL",3,"OFFLINE","B offline: A chờ nối máy","call",requires=("probe:ringback",),checks=("connecting_offline","ringback_signal_started","ringback_signal_stopped"),variant="offline")
    add("CALL",4,"RINGING","A chờ B: trạng thái và chuông gọi đi","call",requires=("probe:ringback",),checks=("outgoing_ringing","ringback_signal_started","ringback_signal_stopped"),variant="ringing")
    for row,mode in ((5,"vibrate"),(6,"normal"),(7,"silent")):
        probe="android_signals" if mode=="normal" else "incoming_alert"
        checks=("incoming","incoming_ringtone_signal") if mode=="normal" else ("incoming","ringer_policy")
        add("CALL",row,mode.upper(),f"Cuộc gọi đến ở chế độ {mode}","call",requires=("probe:"+probe,),checks=checks,
            variant="ringer_system" if mode=="normal" else "ringer",ringer=mode)
    for row,kind,group in ((8,"audio",False),(9,"audio",True),(10,"video",False),(11,"video",True)):
        add("CALL",row,"SERVICE",f"Gọi {kind} {'nhóm' if group else '1–1'} và notification service","call",
            roles=("A","B","C") if group else ("A","B"),
            requires=("group:primary","lab:member_names") if group else (),
            checks=("both_connected","ongoing_service_notification","both_ended"),variant="basic",kind=kind,group=group)
    for row,kind in ((12,"video"),(13,"audio")):
        add("CALL",row,"CALLER_BACKGROUND",f"A gọi {kind}, ra nền trước khi B nghe","call",checks=("background_before_answer","both_connected","ongoing_service_notification"),variant="caller_background",kind=kind)
    for state in ("inapp","background","killed","locked"):
        add("CALL",15,state.upper(),f"Audio đến khi B {state}, mic/loa/tai nghe","call",requires=("probe:audio_duplex","probe:audio_routes"),checks=("both_connected","audio_duplex","mic_toggle","route_switch","wired_bluetooth_hotplug","volume_change"),variant="audio_controls",state=state)
    for row,variant,name in ((16,"offline_missed","B bật mạng sau khi A tắt: chỉ còn cuộc gọi nhỡ"),(17,"cancel_immediate","A hủy ngay sau bấm gọi"),(18,"rapid_repeat","Gọi nhiều lần liên tiếp"),(19,"cold_start","Gọi khi A vừa mở app"),(20,"same_caller_retry","A gọi lại ngay sau B từ chối"),(21,"receiver_recall","B từ chối rồi gọi lại ngay"),(22,"timeout","Không trả lời: timeout và cuộc gọi nhỡ")):
        add("CALL",row,"FUNCTIONAL",name,"call",checks={16:("missed_after_reconnect","no_stale_incoming","fresh_missed_notification"),17:("cancelled","missed_notification","fresh_missed_notification"),18:("repeat_connected",),19:("cold_start_connected",),20:("reject_then_reconnect",),21:("reverse_connected",),22:("timeout_ended","unreachable","missed_notification","fresh_missed_notification")}[row],variant=variant)
    for row,variant in ((23,"busy_ringing"),(24,"busy_then_answer"),(25,"third_reject"),(26,"third_accept")):
        for target in (("A","B") if row in (25,26) else ("B",)):
            add("CALL",row,"THREE_DEVICES_"+target,f"Ba máy: {variant}, C gọi {target}","third_call",roles=("A","B","C"),requires=("lab:member_names",),checks=("third_call_policy","original_call_policy","new_call_policy"),variant=variant,target=target)
    for state in ("inapp","background","locked","killed"):
        for kind in ("audio","video"):
            add("CALL",27,f'{state.upper()}_{kind.upper()}',f"Từ chối {kind} khi B {state}","call",checks=("incoming","rejected","caller_rejection_reason"),variant="reject",state=state,kind=kind)
    add("CALL",28,"NETWORK_LOSS","Mất mạng đang gọi, timeout 30s và cleanup","call",requires=("probe:audio_duplex",),checks=("network_warning","network_timeout","duration_record","audio_stopped","returned_to_chat","no_crash"),variant="network_loss")
    add("CALL",29,"RECENTS_DISMISS","Bỏ app khỏi recents khi đang gọi Android","call",requires=("probe:audio_duplex",),checks=("recents_dismissed","call_survives","audio_duplex"),variant="recents")
    add("CALL",30,"MULTITASK","Call: nền, app khác, PiP, khóa/mở khóa","call",requires=("lab:multitask_package","probe:audio_duplex"),checks=("background_survives","other_app_survives","pip_restored","lock_survives","audio_duplex"),variant="multitask")
    add("CALL",31,"AUDIO_FOCUS","Nhạc/video nhường audio focus cho Call","call",requires=("probe:media_audio_focus",),checks=("media_playing_before","media_paused_or_ducked","call_audio_priority"),variant="media_focus")
    add("CALL",32,"BUBBLE","Gọi lại từ bubble cuộc gọi nhỡ/thoại","call",checks=("call_bubble","bubble_recall_connected"),variant="bubble")
    add("CALL",34,"SLEEP","B sleep trên 5 phút vẫn nhận gọi","call",checks=("slept_over_5_minutes","incoming","both_connected"),variant="sleep",sleep_seconds=330)
    add("CALL",35,"MEETING","Meet: tạo/join/rời/end/share, cam/mic, member mobile/web","meeting",requires=("probe:meeting_web","probe:meeting_media"),checks=("meeting_created","joined","member_identity","camera_mic_state","screen_shared","left","ended","web_participant"))
    for row,caller in ((36,"A"),(37,"B")):
        add("CALL",row,"ANDROID_ANDROID",f"{caller} gọi: bên kia từ chối và gọi ngược","call",requires=("probe:audio_duplex",),checks=("first_ended","reverse_connected","audio_duplex"),variant="receiver_recall",caller=caller)
    for row,meeting in ((40,False),(41,True)):
        for camera_off in (False,True):
            add("CALL",row,"CAMERA_OFF" if camera_off else "CAMERA_ON",f"{'Meet' if meeting else 'Video'} >15 phút, camera off={camera_off}","long_call",requires=("group:primary",) if meeting else (),checks=("connected_over_15_minutes","both_screens_awake"),meeting=meeting,camera_off=camera_off,hold_seconds=910)
    add("CALL",42,"VIDEO_MEDIA","Video 1–1: audio hai chiều và video hai phía","call",requires=("probe:audio_duplex","probe:video_duplex"),checks=("both_connected","audio_duplex","video_frames_both_sides"),variant="video_media",kind="video")
    add("CALL",43,"BACKGROUND_REJECT_RETRY","A ra nền, B tắt: dọn service và gọi mới","call",checks=("caller_background","service_removed","next_call_connected"),variant="background_reject_retry")
    for case in cases:
        requirements=list(case["requirements"])
        flow=case["params"]["flow"]
        if flow in ("meeting","group_lifecycle"):requirements.append("lab:member_names")
        if flow=="media" and not case["params"].get("reject"):requirements.append("probe:media_integrity")
        if flow=="location":requirements.append("probe:location_live" if case["params"].get("live") else "probe:location_destination")
        if flow=="inapp_notification" and case["params"]["variant"]=="same_conversation":requirements.append("group:primary")
        if flow=="typing":requirements.append("locator:typing")
        if flow=="tammi":requirements.append("lab:tammi_ai_consent_acknowledged")
        if flow in ("unread","unread_banner"):requirements.append("locator:conversation_unread_count")
        if flow=="call" and case["params"].get("variant")=="network_loss":requirements.append("locator:call_bubble_duration")
        if flow=="long_call":
            requirements.append("probe:camera_capture")
            case["obligations"]+=("camera_state_confirmed",)
        if flow=="group_lifecycle":requirements.extend(("account:C","member_name:C"))
        case["requirements"]=tuple(requirements)
    for case in cases:
        if "probe:audio_duplex" in case["requirements"]:
            names={"audio_duplex":"call_audio_signals","audio_stopped":"call_audio_mode_released"}
            case["obligations"]=tuple(names.get(assertion,assertion) for assertion in case["obligations"])
            case["coverage_level"]="partial"
            case["note"]="Kiểm tra tín hiệu thoại của Android theo UID trên A/B, chưa đo nội dung, chất lượng âm hoặc độ trễ."
        if "probe:ringback" in case["requirements"]:
            case["coverage_level"]="partial"
            case["note"]="PASS tín hiệu ADB trước–trong–sau theo UID/player; không đo RMS/SNR hay chất lượng âm vật lý. Volume/route thiếu được ghi unavailable."
        elif case["id"]=="CALL-006-NORMAL":
            case["coverage_level"]="partial"
            case["note"]="Kiểm tra màn hình gọi đến và player chuông mới theo UID trên Android."
        elif case["id"]=="CHAT-004-VOICE":
            case["coverage_level"]="partial"
            case["note"]="Kiểm tra nhận tin thoại mới và vòng đời player phát lại trên Android theo UID."
        elif "probe:notification_alert" in case["requirements"]:
            case["coverage_level"]="partial"
            case["note"]="Xác minh push, dispatch chuông/rung đúng notification key và mở đúng hội thoại. Chưa đo chuông/rung vật lý."
    return cases
