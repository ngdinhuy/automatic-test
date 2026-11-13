"""Điều phối bộ chức năng đầy đủ; assertion chỉ được ghi sau hành vi quan sát thực tế."""
import hashlib
import json
import re
import time
import uuid
from pathlib import Path

from .common import ROOT, Blocked, validate_devices, list_devices
from .device import Devices
from .probes import command, measure
from .suite_ui import UI
from .pages import literal


def file_sha256(path):
    digest=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):digest.update(block)
    return digest.hexdigest()


def preflight(config, case, available=None):
    if (ROOT/".runtime/device-restore.json").exists():raise Blocked("Còn journal trạng thái Android; chạy scripts/recover.sh trước.")
    validate_devices(config, available if available is not None else list_devices(config), case.roles)
    missing=[]
    if case.params.get("flow")=="location" and config.get("environment")!="prod":missing.append("Location chỉ kiểm thử trên prod theo yêu cầu; không chạy staging.")
    for requirement in case.requirements:
        kind,key=requirement.split(":",1)
        if kind=="probe":
            try:command(config,key)
            except Blocked as error:missing.append(str(error))
            supported=config.get("lab",{}).get("probes",{}).get(key,{}).get("supported_media")
            if key=="media_integrity" and supported is not None and case.params.get("media") not in supported:
                missing.append("Adapter media hiện chưa hỗ trợ "+str(case.params.get("media")))
        elif kind=="fixture":
            fixture=config.get("fixtures",{}).get(key)
            if not isinstance(fixture,dict):missing.append("Thiếu fixture "+key);continue
            if key not in ("camera_photo","camera_video"):
                path=Path(fixture.get("path","")).expanduser()
                if not path.is_absolute():path=ROOT/path
                if not path.is_file():missing.append("Không tìm thấy file fixture "+key)
                elif fixture.get("sha256") and file_sha256(path)!=fixture["sha256"]:missing.append("SHA256 fixture không khớp "+key)
                elif key=='gallery_video' and path.stat().st_size<=100*1024*1024:missing.append('Case video lớn cần file nguồn >100 MiB.')
                elif key=="video_over_1000mb" and path.stat().st_size<=1000*1024*1024:missing.append("Fixture video phải >1000 MiB")
                elif key=="image_over_20mb" and path.stat().st_size<=20*1024*1024:missing.append("Fixture ảnh phải >20 MiB")
                elif key=="image_under_100mb" and path.stat().st_size>=100*1024*1024:missing.append("Fixture nén phải <100 MiB")
        elif kind=="limit":
            value=config.get("limits",{}).get(key)
            if not isinstance(value,int) or isinstance(value,bool) or value<1:missing.append("Cần giới hạn ký tự đã xác nhận: "+key)
        elif kind=="locator":
            if not config.get("locators",{}).get(key):missing.append("Cần locator đã hiệu chỉnh: "+key)
        elif kind=="group":
            if not config.get("groups",{}).get(key):missing.append("Chọn nhóm test trong Thiết lập: "+key)
        elif kind=="account":
            if not config.get("devices",{}).get(key,{}).get("account",{}).get("phone"):missing.append("Cần tài khoản staging "+key+" để chọn đủ thành viên tạo nhóm; chưa cần cắm máy C.")
        elif kind=="member_name":
            if not config.get("lab",{}).get("member_names",{}).get(key):missing.append("Cần tên đã xác minh lab.member_names."+key)
        elif kind=="lab":
            value=config.get("lab",{}).get(key)
            if not value:missing.append("Thiếu điều kiện lab: "+key)
            elif key=="member_names" and (not isinstance(value,dict) or any(not value.get(role) for role in case.roles)):missing.append("member_names cần đủ tên cho các vai "+", ".join(case.roles))
        else:missing.append("Loại điều kiện chưa được hỗ trợ: "+requirement)
    state=case.params.get("state")
    if (state in ("locked","killed_locked","sleep") or case.params.get("variant") in ("sleep","multitask")) and not config.get("lab",{}).get("unsecured_devices"):
        missing.append("Case khóa/sleep cần lab.unsecured_devices=true sau khi tắt PIN sinh trắc học trên máy test")
    if missing:raise Blocked("; ".join(missing))


class FullRun:
    def __init__(self, ctx, case):
        self.ctx,self.case,self.p=ctx,case,case.params
        self.marker="APPIUM-"+uuid.uuid4().hex[:12]
        self.done=set();self.pages={};self.uis={}
        if not getattr(ctx,"devices_control",None):ctx.devices_control=Devices(ctx)
        self.devices=ctx.devices_control

    def page(self,role):
        if role not in self.pages:
            page=self.ctx.page(role);page.login_and_verify()
            self.pages[role]=page;self.uis[role]=UI(page,{"marker":self.marker})
        return self.pages[role]

    def ui(self,role):self.page(role);return self.uis[role]
    def record(self,*names):
        self.done.update(names)
        self.ctx.assertion_results[self.case.id]=sorted(self.done)
        for name in names:self.ctx.reporter.emit("assertion",name,case_id=self.case.id)
    def probe(self,name,**values):return measure(self.ctx,name,**{"case_id":self.case.id,"marker":self.marker,**values})

    def open(self,role,context=None,peer=None):
        page=self.page(role)
        if context=="group":self.ui(role).open_named(self.ctx.config["groups"]["primary"])
        else:page.open_peer(peer_role=peer)
        return page

    def pair(self,context=None):
        return self.open("A",context),self.open("B",context)

    def send(self,sender="A",receiver="B",message=None):
        text=message or self.marker
        self.page(sender).send(text);self.page(receiver).message_received(text)
        return text

    def absent_message(self,role,message):
        page=self.page(role);value=page.text_locator(message)
        page.wait(lambda: not page.elements(value),"Nội dung cũ vẫn hiển thị ở "+role)

    def finish(self):
        missing=set(self.case.obligations)-self.done
        if missing:raise RuntimeError("Handler chưa chứng minh đủ assertion: "+", ".join(sorted(missing)))
        return "Đã chứng minh: "+", ".join(self.case.obligations)

    def marker_count(self,role):
        value=literal(self.marker)
        return len(self.page(role).elements('//*[contains(@text,'+value+') or contains(@content-desc,'+value+')]'))

    def chat(self):
        flow=self.p["flow"];a,b=self.pair()
        if flow=="cache":
            self.send();self.record("received_online")
            self.devices.network("B",False);name=b.peer_name;b.home()
            b.click('//*[starts-with(@content-desc,'+literal(name+",")+')]')
            b.composer();b.message_received(self.marker)
            self.record("cached_offline");return
        if flow=="text":
            length=700 if self.p["length"]=="medium" else self.ctx.config["limits"]["text_max"]
            for sender,receiver,suffix in (("A","B","A"),("B","A","B")):
                prefix=self.marker+suffix+" "
                if length<len(prefix):raise Blocked("text_max nhỏ hơn marker để đối chiếu duy nhất.")
                payload=(prefix+"Nội dung kiểm thử 0123456789 "*length)[:length]
                self.send(sender,receiver,payload)
            self.record("exact_payload_both_directions");return
        if flow=="offline_send":
            self.devices.network("A",False)
            self.type_owned("A",self.marker);self.ui("A").click("send")
            self.release_draft_if_empty("A");self.ui("A").find("offline_error",timeout=45)
            self.record("offline_error");self.devices.network("A",True)
            if not self.ui("A").exists("retry"):
                b.message_received(self.marker)
                raise Blocked("App tự gửi lại ngay khi có mạng; đã nhận tin nhưng chưa chứng minh thao tác retry thủ công.")
            retry='//*[contains(@content-desc,'+literal(self.marker)+')]/ancestor::*[.//*[@content-desc="Gửi lại"]][1]//*[@content-desc="Gửi lại"]'
            a.click(retry);b.message_received(self.marker)
            source=b.driver.page_source
            import xml.etree.ElementTree as ET
            matches=[n for n in ET.fromstring(source).iter() if self.marker in (n.get("text","")+n.get("content-desc","")) and not n.get("class","").endswith("EditText")]
            assert len(matches)==1,"Tin retry bị nhân đôi hoặc chưa có đúng một bubble."
            self.record("retry_delivered_once");return
        if flow=="draft_send":
            self.type_owned("A",self.marker);a.home();self.preview("A",self.marker)
            self.record("draft_preview");a.open_peer()
            a.wait(lambda:a.composer().get_attribute("text")==self.marker,"Nháp chưa khôi phục đúng.")
            self.record("draft_restored");self.ui("A").click("send");self.release_draft_if_empty("A")
            b.message_received(self.marker);self.record("sent")
            a.home();row=self.preview("A",self.marker)
            assert "nháp" not in row.lower(),"Last message vẫn có nhãn nháp sau gửi."
            self.record("draft_badge_removed");return
        if flow=="last_message":
            self.send();self.record("received");b.home();self.preview("B",self.marker);self.record("conversation_preview");return
        if flow=="typing":
            self.type_owned("A",self.marker);self.ui("B").find("typing",timeout=10);self.record("typing_visible")
            a.clear_owned_draft();self.ui("B").absent("typing",timeout=15);self.record("typing_cleared");return
        if flow in ("forward","edit","delete","pin_message","search_message","reaction"):
            self.send();u=self.ui("A")
            if flow=="search_message":
                u.profile();u.click("profile_search");u.fill("search_input",self.marker);u.message(self.marker)
                self.record("search_exact_payload");return
            marker_counts={role:self.marker_count(role) for role in ("A","B")}
            u.menu(self.marker)
            if flow=="edit":
                u.click("edit");u.fill("search_input",self.marker+" edited");u.click("edit_confirm")
                for p in (a,b):p.message_received(self.marker+" edited")
                self.record("edited_both_sides")
                for role in ("A","B"):
                    source=self.page(role).driver.page_source
                    assert f'content-desc="{self.marker}.' not in source,"Bubble cũ chưa cập nhật."
                self.record("old_payload_absent")
            elif flow=="delete":
                u.click("revoke")
                if a.elements(a.text_locator("Bạn chắc chắn muốn thu hồi tin nhắn đã chọn")):u.click("revoke")
                for role in ("A","B"):
                    self.ui(role).page.wait(lambda r=role:self.marker not in self.page(r).driver.page_source,"Tin test chưa biến mất ở "+role)
                    self.ui(role).find("deleted")
                self.record("deleted_both_sides")
            elif flow=="pin_message":
                if not u.exists("pin"):u.click("menu_more")
                pin_pending=[True]
                def remove_owned_pin():
                    if not pin_pending[0]:return
                    a.open_peer();u.menu(self.marker)
                    if not u.exists("unpin") and u.exists("menu_more"):u.click("menu_more")
                    if u.exists("unpin"):
                        u.click("unpin")
                        if u.exists("confirm"):u.click("confirm")
                    pin_pending[0]=False
                self.ctx.suite_cleanup.append(remove_owned_pin)
                u.click("pin")
                if u.exists("confirm"):u.click("confirm")
                pinned='//*[contains(@content-desc,'+literal(self.marker)+')]/parent::*//*[@text="Đã ghim" or @content-desc="Tin Nhắn Đã Ghim"]'
                for role in ("A","B"):self.page(role).find(pinned)
                self.record("pinned_payload");u.menu(self.marker)
                if not u.exists("unpin"):u.click("menu_more")
                u.click("unpin")
                if u.exists("confirm"):u.click("confirm")
                for role in ("A","B"):self.page(role).wait(lambda r=role:not self.page(r).elements(pinned),"Tin test vẫn còn nhãn ghim ở "+role)
                pin_pending[0]=False
                self.record("unpinned_payload")
            elif flow=="forward":
                u.click("forward");u.fill("search_input",a.peer_name)
                u.click("member_result",member=a.peer_name);u.click("send")
                b.wait(lambda:self.marker_count("B")>marker_counts["B"],"B chưa có thêm bản chuyển tiếp mới của tin test.")
                self.record("forwarded_payload")
            else:
                u.click("reaction");self.ui("B").find("reaction_details")
                self.ui("B").click("reaction_details");self.ui("B").find("reaction_sheet");self.record("reaction_added");self.ui("B").find("reactor",member=self.member_name("A"));self.record("reactor_identity")
                self.ui("B").find("reaction_count_one");self.record("reaction_count")
                # Bottom sheet đánh dấu reaction của chính A bằng “Nhấn để gỡ”; không suy icon từ số node.
                b.driver.back();u.click("reaction_details");u.click("reaction_remove")
                self.ui("B").absent("reaction_details");self.record("reaction_removed")
            return
        raise RuntimeError("Flow Chat không có nhánh: "+flow)

    def member_name(self,role):
        name=self.ctx.config.get("lab",{}).get("member_names",{}).get(role)
        if not name:
            peer=self.ctx.page("B" if role=="A" else "A")
            # Tên hội thoại nhóm không phải danh tính thành viên cần đối chiếu.
            if peer.peer_role==role and not peer.conversation_name:name=peer.peer_name
        if not name:raise Blocked("Cần lab.member_names."+role+" hoặc mở hội thoại peer để xác minh tên thành viên.")
        return name

    def type_owned(self,role,text):
        page=self.page(role);old=page.composer().get_attribute("text") or ""
        if old not in ("","Nhập tin nhắn"):raise Blocked("Có nháp sẵn; không ghi đè.")
        page.draft_journal(page.draft_journal()+[text]);page.owned_draft=text
        page.composer().send_keys(text)
        page.wait(lambda:page.composer().get_attribute("text")==text,"Ô nhập chưa giữ đúng nội dung test.")

    def release_draft_if_empty(self,role):
        page=self.page(role)
        if page.composer().get_attribute("text") in ("","Nhập tin nhắn"):
            text=page.owned_draft;page.owned_draft=None
            page.draft_journal([value for value in page.draft_journal() if value!=text])

    def preview(self,role,marker):
        page=self.page(role);element=self.ui(role).message(marker)
        text=element.get_attribute("content-desc") or element.get_attribute("text")
        assert marker in text,"Preview không giữ đầy đủ marker."
        return text

    def incoming_state(self,role):
        self.devices.state(role,self.p.get("state","inapp"),self.p.get("sleep_seconds",0))

    def notification(self):
        flow=self.p["flow"];a,b=self.pair()
        if flow=="inapp_notification":
            if self.p["variant"]=="other_conversation":
                from concurrent.futures import ThreadPoolExecutor
                group=self.ctx.config['groups']['primary'];self.ui('B').open_named(group)
                assert group!=self.ctx.config.get('lab',{}).get('member_names',{}).get('A'),'Cần hội thoại nhóm khác hội thoại peer.'
                # Theo dõi B ngay lúc A gửi vì banner chỉ hiện trong vài giây.
                with ThreadPoolExecutor(max_workers=1) as worker:
                    incoming=worker.submit(self.ui('B').find,'inapp_message_banner',marker=self.marker,timeout=35)
                    a.send(self.marker);incoming.result()
                b.find(b.text_locator(group))
            else:
                from .notification_lab import same_conversation
                same_conversation(self,a,b)
            self.record("inapp_notification_policy");return
        b.home()
        if flow=="unread_banner":
            badge=self.ctx.config["locators"]["conversation_unread_count"]
            b.wait(lambda:not b.elements(badge),"Chưa xác minh unread của hội thoại B về 0 trước khi tạo 3 tin mới.")
        if flow=="notification":self.incoming_state("B")
        else:self.devices.state("B","background")
        count=3 if flow in ("unread","unread_banner") else 1
        if flow=="notification":self.probe("notification_alert",phase="prepare",stage="baseline")
        for i in range(count):a.send(self.marker+f"-{i}")
        self.devices.wake("B")
        if flow=="unread_banner":
            b.driver.activate_app(self.ctx.config['app_package']);b.home()
            def correct_unread():
                nodes=b.elements(badge)
                labels=[(node.get_attribute('content-desc') or '')+' '+(node.get_attribute('text') or '') for node in nodes]
                return len(nodes)==1 and any(re.search(r'\b'+str(count)+r' tin nhắn chưa đọc\b',label) for label in labels)
            try:b.wait(correct_unread,'Không đọc được đúng 3 unread của hội thoại đã tạo tin; cần semantics stateDescription.',timeout=15)
            except AssertionError as error:raise Blocked(str(error)) from error
            self.ctx.reporter.emit('assertion','Đúng hội thoại B có 3 unread trước khi mở push.',case_id=self.case.id)
        u=self.ui("B");u.notification(self.marker)
        if flow=="notification":
            self.record("notification_payload")
            values=self.probe("notification_alert",state=self.p["state"])
            assert values["sound_dispatched"]==1,"Android chưa dispatch chuông cho đúng thông báo."
            assert values["vibration_dispatched"]==1,"Android chưa dispatch rung cho đúng thông báo."
            self.record("notification_alert_dispatch")
        if flow=="notification_clear":self.record("notification_before")
        if flow=="unread":
            values=self.probe("launcher_badge",expected_count=count)
            assert values["count"]==count,"Badge launcher sai số unread."
            self.record("badge_count")
        u.open_notification(self.marker);b.message_received(self.marker+f"-{count-1}")
        if flow=="notification":self.record("open_correct_conversation")
        if flow=="notification_clear":
            self.record("correct_conversation");b.driver.open_notifications()
            b.wait(lambda:self.marker not in b.driver.page_source,"Push còn lại sau khi đọc tin.");b.driver.back();self.record("notification_removed")
        if flow=="unread_banner":
            text=u.find("unread_banner").get_attribute("text")
            assert re.search(rf"\b{count}\b",text),"Unread banner sai số tin."
            self.record("unread_banner_exact_count")
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                self.ctx.check()
                banners=u.exists("unread_banner")
                assert banners,"Unread banner mất ngay trong cửa sổ quan sát 3 giây."
                assert any(re.search(rf"\b{count}\b",node.get_attribute("text") or node.get_attribute("content-desc") or "") for node in banners),"Unread banner đổi sai số tin."
                time.sleep(.25)
            self.record("unread_banner_persists_3s")
        if flow=="unread":
            b.home();row=self.preview("B",self.marker)
            badge=self.ctx.config.get("locators",{}).get("conversation_unread_count")
            if not badge:raise Blocked("Cần locator unread count của row hội thoại để đối chiếu chính xác.")
            # Tin đã đọc qua push phải được xóa unread; số trước đọc lưu từ probe và notification.
            assert not b.elements(badge),"Unread không về 0 sau khi đọc."
            self.record("read_clears_count")
            values=self.probe("launcher_badge",expected_count=0)
            assert values["count"]==0,"Badge launcher chưa về 0 sau khi đọc."
            # Kiểm tra độc lập lại số trước đọc, tránh suy từ badge launcher.
            b.home()
            for i in range(count):a.send(self.marker+f"-unread-{i}")
            element=b.find(badge);assert int(re.sub(r"\D","",element.get_attribute("text")))==count
            self.record("unread_exact_count")

    def start_call(self,caller="A",receiver="B",kind="audio"):
        a,b=self.open(caller,peer=receiver),self.open(receiver,peer=caller)
        for page in (a,b):
            if page.elements(page.named("call_end")) or page.elements(page.named("call_reject")):
                raise Blocked("Đang có cuộc gọi sẵn; không can thiệp.")
        self.ctx.owned_call_roles.update((caller,receiver))
        a.call_control("call_"+kind)
        return a,b

    def start_group_call(self,caller,receivers,kind):
        a=self.page(caller);u=self.ui(caller)
        u.click('group_call_menu');u.click('group_'+kind)
        lab=self.ctx.config['lab']
        viewer_names=lab.get('member_names_by_viewer',{}).get(caller,{})
        names=[viewer_names.get(role) or lab['member_names'].get(role) for role in receivers]
        if not all(names) or len(set(names))!=len(receivers):
            raise Blocked('Cần tên thành viên riêng biệt đã xác minh trước khi gửi lời mời.')
        for name in names:
            a.find(a.text_locator(name),timeout=30)
        clear=a.text_locator('Bỏ chọn tất cả')
        if a.elements(clear):
            self.ctx.reporter.emit('step','Đã tải màn mời nhóm; bỏ lựa chọn mặc định')
            a.click(clear)
            a.find(a.text_locator('Chọn tất cả'))
        for name in names:
            locator=a.text_locator(name)
            if len([element for element in a.elements(locator) if element.is_displayed()])!=1:
                raise Blocked('Không định vị được duy nhất thành viên cần mời trong nhóm test.')
            a.click(locator,stable_bounds=True)
        a.find(f'//*[starts-with(@text,"Đã chọn: {len(receivers)}/")]')
        self.ctx.reporter.emit('step',f'{caller}: chọn vai '+', '.join(receivers)+' trong lời mời gọi nhóm')
        a.click('//*[@content-desc="Gửi lời mời"]/ancestor-or-self::*[@clickable="true"][1]',stable_bounds=True)
        a.wait(lambda:a.call_service_active() or a.elements(a.named('call_end')),'Chưa xác minh cuộc gọi nhóm đã bắt đầu sau gửi lời mời.',timeout=30)

    def group_service_call(self,caller,kind):
        receivers=tuple(role for role in self.case.roles if role!=caller)
        participants=[self.open(role,"group") for role in (caller,*receivers)]
        for page in participants:
            page.require_idle_call()
        self.ctx.owned_call_roles.update(self.case.roles)
        self.start_group_call(caller,receivers,kind)
        for page in participants[1:]:
            page.call_control("call_accept")
        for page in participants:
            page.wait_connected()
        self.record("both_connected")
        for page in participants:
            self.service(page.role)
        self.record("ongoing_service_notification")
        for page in participants:
            if page.call_active():
                page.end_owned_call()
        self.ended(*participants)
        self.ctx.owned_call_roles.difference_update(self.case.roles)
        self.record("both_ended")

    def answer(self,caller,receiver):
        receiver.wait_incoming()
        if "incoming" in self.case.obligations:self.record("incoming")
        receiver.call_control("call_accept")
        # Chỉ đưa A trở lại sau khi B đã nghe; giai đoạn A ở nền trước khi nghe vẫn được giữ nguyên.
        if self.p.get("variant")=="caller_background":
            caller.open_owned_call_notification()
        for page in (caller,receiver):page.wait_connected()

    def ended(self,*pages,timeout=35):
        for page in pages:page.wait(lambda p=page:not p.call_active(),"Cuộc gọi/PiP/service còn active.",timeout)

    def stop_call(self,a,b):
        a.end_owned_call();self.ended(a,b);self.ctx.owned_call_roles.difference_update((a.role,b.role))

    def new_missed_notification(self, role, before):
        page=self.page(role)
        def fresh():
            current=self.devices.missed_notifications(role,page.peer_name)
            return any(updated>before.get(key,-1) for key,updated in current.items())
        page.wait(fresh,"Không có notification cuộc gọi nhỡ mới của peer sau hành động test.",timeout=40)
        self.ui(role).notification("Cuộc gọi")
        self.ui(role).find("missed_call")
        self.ctx.reporter.emit("assertion",role+": notification nhỡ có phiên bản mới, không dùng notification cũ.",case_id=self.case.id)
        self.record("fresh_missed_notification")

    def service(self,role,present=True):
        page=self.page(role);page.driver.open_notifications()
        # ColorOS dùng thẻ call với tên, chronometer và Gác máy; không hiện body notification.
        peer=literal(page.peer_name or "")
        card='//*[@text='+peer+']/ancestor::*[.//*[contains(@resource-id,"chronometer")] and .//*[@content-desc="Gác máy" or @content-desc="Kết thúc" or @text="Gác máy" or @text="Kết thúc"]][1]'
        body='//*[contains(@text,"Đang trong cuộc gọi") or contains(@text,"Cuộc gọi đang diễn ra")]'
        locator=self.ctx.config.get("locators",{}).get("ongoing_call_notification") or card+' | '+body
        try:
            if present:page.find(locator)
            else:page.wait(lambda:not page.elements(locator),"Service notification chưa được dọn.")
        finally:self.devices.adb(role,"shell","cmd","statusbar","collapse")

    def call(self):
        variant=self.p.get("variant","basic");caller=self.p.get("caller","A");receiver="B" if caller=="A" else "A"
        kind=self.p.get("kind","audio");group=self.p.get("group",False)
        if group:
            self.group_service_call(caller,kind)
            return
        if variant=="cold_start":
            self.page(caller).driver.terminate_app(self.ctx.config["app_package"])
            self.page(caller).driver.activate_app(self.ctx.config["app_package"])
        a,b=self.open(caller,peer=receiver),self.open(receiver,peer=caller)
        missed_before=self.devices.missed_notifications(receiver,b.peer_name) if variant in ("offline_missed","cancel_immediate","timeout") else {}
        if variant in ("offline","offline_missed"):self.devices.network(receiver,False)
        if variant in ("ringer","ringer_system"):self.devices.ringer(receiver,self.p["ringer"])
        if variant=="sleep":self.devices.state(receiver,"sleep",self.p["sleep_seconds"]);self.record("slept_over_5_minutes")
        elif self.p.get("state"):self.incoming_state(receiver)
        for page in (a,b):
            if page.elements(page.named("call_end")):raise Blocked("Có cuộc gọi sẵn trước testcase.")
        if 'probe:ringback' in self.case.requirements:self.probe('ringback',phase='prepare',stage='baseline',role=caller)
        if 'probe:audio_duplex' in self.case.requirements:
            self.probe('audio_duplex',phase='prepare',stage='baseline')
        if 'probe:audio_routes' in self.case.requirements:
            from .audio_devices import connected
            hardware=connected(self.devices.adb(caller,'shell','dumpsys','audio'))
            if not hardware['bluetooth_call_profiles'] or not hardware['wired_output']:
                raise Blocked('Cần Android nhận cả Bluetooth thoại và tai nghe dây/USB trước khi chạy.')
            self.probe('audio_routes',phase='prepare',stage='baseline',role=caller)
        if variant=='ringer_system':
            # Chụp mốc ngay trước cuộc gọi, loại notification đến trong lúc xác minh tài khoản.
            self.probe('android_signals',phase='prepare',role=receiver)
        self.ctx.owned_call_roles.update((caller,receiver))
        a.call_control("call_"+kind)
        if variant=="offline":
            self.ui(caller).find("connecting");self.record("connecting_offline")
            self.probe("ringback",role=caller)
            self.stop_call(a,b)
            self.probe("ringback",phase="after",role=caller)
            self.record("ringback_signal_started","ringback_signal_stopped");return
        if variant=="offline_missed":
            self.ui(caller).find("connecting");a.end_owned_call();self.devices.network(receiver,True)
            self.new_missed_notification(receiver,missed_before);self.record("missed_after_reconnect")
            self.devices.wake(receiver);b.driver.activate_app(self.ctx.config["app_package"])
            assert not b.elements(b.named("call_accept")),"Incoming cũ xuất hiện sau reconnect."
            self.record("no_stale_incoming");return
        if variant=="cancel_immediate":
            a.call_control("call_end");self.ended(a,b);self.record("cancelled")
            self.new_missed_notification(receiver,missed_before);self.record("missed_notification");return
        self.devices.wake(receiver)
        if variant=="ringing":
            b.wait_incoming();self.ui(caller).find("outgoing_ringing");self.record("outgoing_ringing")
            self.probe("ringback",role=caller)
            self.answer(a,b)
            self.probe("ringback",phase="after",role=caller)
            self.stop_call(a,b)
            self.record("ringback_signal_started","ringback_signal_stopped");return
        if variant=='ringer_system':
            b.wait_incoming();self.record('incoming')
            values=self.probe('android_signals',role=receiver)
            mode=self.p['ringer']
            if mode=='vibrate':assert values['fresh_vibration_events']>=1,'Không có sự kiện rung mới được Android chấp nhận cho app.'
            if mode=='normal':
                assert values['active_ringtone_clients']>=1,'Không đo được MediaPlayer/RINGTONE của app đang phát trong cửa sổ lấy mẫu.'
                if 'incoming_ringtone_signal' in self.case.obligations:
                    self.record('incoming_ringtone_signal')
                    return
            if mode=='silent':
                assert values['fresh_vibration_events']==0 and values['active_ringtone_clients']==0,'Silent vẫn có rung/phát ringtone ở tầng Android.'
            self.record('system_alert_policy');return
        if variant=="ringer":
            b.wait_incoming();self.record("incoming");values=self.probe("incoming_alert",mode=self.p["ringer"])
            mode=self.p["ringer"]
            assert (values["ringer_rms"]<.001 if mode!="normal" else values["ringer_rms"]>=.001),"Chuông không đúng ringer mode."
            assert values["vibration_events"]>=1 if mode=="vibrate" else True
            if mode=="silent":assert values["vibration_events"]==0,"Silent vẫn rung."
            self.record("ringer_policy");return
        if variant=="timeout":
            b.wait_incoming()
            status=self.ui(caller).find("timeout_result",timeout=150)
            actual=status.get_attribute("text") or status.get_attribute("content-desc") or ""
            self.ended(a,b,timeout=35);self.record("timeout_ended")
            self.new_missed_notification(receiver,missed_before);self.record("missed_notification")
            assert "không liên lạc được" in actual.lower(),"Thông báo timeout khác expected Excel: "+actual
            self.record("unreachable");return
        if variant in ("receiver_recall","same_caller_retry","reject","bubble","background_reject_retry"):
            if variant=="background_reject_retry":a.driver.press_keycode(3);self.record("caller_background")
            b.wait_incoming()
            if variant=="reject":self.record("incoming")
            b.call_control("call_reject")
            if variant=="reject":
                self.ended(a,b);self.record("rejected");self.ui(caller).find("rejected_reason");self.record("caller_rejection_reason");return
            if variant=="background_reject_retry":
                self.service(caller,False);self.record("service_removed");a.driver.activate_app(self.ctx.config["app_package"])
            if variant=="receiver_recall":
                b.call_control("call_"+kind);a.call_control("call_accept")
                for page in (a,b):page.wait_connected()
                self.record("first_ended","reverse_connected")
                if "probe:audio_duplex" in self.case.requirements:self.probe("audio_duplex");self.record("call_audio_signals")
            else:
                a.home();self.open(caller,peer=receiver)
                if variant=="bubble":self.ui(caller).click("call_bubble");self.record("call_bubble")
                else:a.call_control("call_"+kind)
                self.answer(a,b)
                self.record({"bubble":"bubble_recall_connected","same_caller_retry":"reject_then_reconnect","background_reject_retry":"next_call_connected"}[variant])
            self.stop_call(a,b);return
        if variant=="caller_background":a.driver.press_keycode(3);self.record("background_before_answer")
        self.answer(a,b)
        if variant in ("basic","caller_background","sleep","video_media"):self.record("both_connected")
        if variant in ("basic","caller_background"):
            for role in (caller,receiver):self.service(role)
            self.record("ongoing_service_notification")
        if variant=="cold_start":self.record("cold_start_connected")
        if variant=="rapid_repeat":
            self.stop_call(a,b)
            for _ in range(4):a,b=self.start_call();self.answer(a,b);self.stop_call(a,b)
            self.record("repeat_connected");return
        if variant=="audio_controls":
            u=self.ui(caller);u.click("mic");u.find("mic_off");u.click("mic");u.absent("mic_off");self.record("mic_toggle")
            self.check_call_routes(a)
            self.probe("audio_duplex");self.record("call_audio_signals","both_connected")
        if variant=="network_loss":
            self.probe("audio_duplex")
            self.devices.network(receiver,False);self.ui(caller).find("network_warning");self.record("network_warning")
            self.ended(a,b,timeout=45);self.record("network_timeout")
            self.devices.network(receiver,True)
            # Probe phải đo sau kết thúc để kiểm tra không còn audio, không dùng số đo đang gọi.
            self.probe("audio_duplex",phase="after_end")
            self.record("call_audio_mode_released")
            for page in (a,b):page.home();page.open_peer();self.ui(page.role).find("call_bubble")
            self.record("returned_to_chat","no_crash")
            duration=self.ctx.config.get("locators",{}).get("call_bubble_duration")
            if not duration:raise Blocked("Cần locator thời lượng bubble để đối chiếu call ended.")
            for page in (a,b):assert re.search(r"\d+",page.find(duration).get_attribute("text"))
            self.record("duration_record");return
        if variant=="recents":
            self.devices.dismiss_recents(caller);self.record("recents_dismissed")
            self.service(caller);self.page(caller).driver.activate_app(self.ctx.config["app_package"])
            a.wait_connected();self.record("call_survives");self.probe("audio_duplex");self.record("call_audio_signals")
        if variant=="multitask":
            a.driver.press_keycode(3);self.service(caller);self.record("background_survives")
            package=self.ctx.config["lab"]["multitask_package"]
            if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.]+",package):raise Blocked("Package lab không hợp lệ.")
            a.driver.activate_app(package);b.wait_connected();self.record("other_app_survives")
            self.ui(caller).click("pip");a.wait_connected();self.record("pip_restored")
            self.devices.state(caller,"locked");b.wait_connected();self.devices.wake(caller);a.wait_connected();self.record("lock_survives")
            self.probe("audio_duplex");self.record("call_audio_signals")
        if variant=="media_focus":
            values=self.probe("media_audio_focus");assert values["media_rms_before"]>0
            self.record("media_playing_before","media_paused_or_ducked","call_audio_priority")
        if variant=="video_media":
            self.probe("audio_duplex");self.record("call_audio_signals");self.probe("video_duplex");self.record("video_frames_both_sides")
        self.ctx.evidence(self.case.id+"-connected");self.stop_call(a,b)
        if variant=="basic":self.record("both_ended")

    def check_call_routes(self, page):
        from .audio_devices import connected

        role=page.role
        ui=self.ui(role)

        def select(label, stage):
            page.click(ui.xpath("speaker"),call_controls=True)
            page.click(page.text_locator(label)+'/ancestor-or-self::*[@clickable="true"][1]',stable_bounds=True)
            self.probe("audio_routes",role=role,stage=stage)

        def wait_for_wired(expected, instruction):
            self.ctx.reporter.emit("step",instruction)
            try:
                page.wait(lambda:connected(self.devices.adb(role,'shell','dumpsys','audio'))['wired_output']==expected,
                          instruction,timeout=35)
            except AssertionError as error:
                raise Blocked(str(error)) from error

        select("Loa ngoài","speaker")
        select("Loa trong","earpiece")
        self.record("route_switch")
        select("Thiết bị Bluetooth","bluetooth")
        wait_for_wired(False,f"Rút tai nghe dây/USB khỏi máy {role} để bắt đầu bước cắm lại.")
        wait_for_wired(True,f"Cắm tai nghe dây/USB vào máy {role} trong 35 giây.")
        select("Tai nghe","wired")
        before=self.probe("audio_routes",role=role,stage="volume")
        for key, undo in ((24,25),(25,24)):
            page.driver.press_keycode(key)
            after=self.probe("audio_routes",role=role,stage="volume")
            assert after["route"]==before["route"], "Route đã đổi trong lúc đo âm lượng thoại."
            if after["volume"]!=before["volume"]:
                page.driver.press_keycode(undo)
                restored=self.probe("audio_routes",role=role,stage="volume")
                assert restored==before, "Chưa khôi phục mức âm lượng của route dây."
                break
        else:
            raise AssertionError("Âm lượng thoại trên route dây chưa đổi.")
        self.record("volume_change")
        wait_for_wired(False,f"Rút tai nghe dây/USB khỏi máy {role} trong 35 giây.")
        self.probe("audio_routes",role=role,stage="wired_removed")
        select("Thiết bị Bluetooth","bluetooth")
        self.record("wired_bluetooth_hotplug")

    def third_call(self):
        variant=self.p["variant"];target=self.p.get("target","B")
        # C có thể chậm: xác minh và mở peer trước khi A/B bắt đầu cửa sổ gọi.
        try:c=self.open("C",peer=target)
        except AssertionError as error:raise Blocked("C chưa mở được hội thoại chuẩn bị trước cuộc gọi: "+str(error)) from error
        a,b=self.start_call()
        waiting=a if target=="A" else b;other=b if target=="A" else a
        if variant in ("third_reject","third_accept"):self.answer(a,b)
        else:b.wait_incoming()
        self.ctx.owned_call_roles.add("C");c.emit("step","C: gọi phụ, theo dõi kết quả tức thời ở máy nhận")
        c.click(c.named("call_audio"),stable_bounds=True)
        if variant in ("busy_ringing","busy_then_answer"):
            self.ui("C").find("busy_reason");self.ended(c);self.record("third_call_policy","new_call_policy")
            if variant=="busy_then_answer":self.answer(a,b)
            else:self.ui("A").find("outgoing_ringing");b.wait_incoming()
            self.record("original_call_policy")
        elif variant=="third_reject":
            waiting.find(waiting.text_locator(self.ctx.config["lab"].get("member_names_by_viewer",{}).get(target,{}).get("C",self.ctx.config["lab"]["member_names"]["C"])))
            waiting.call_control("call_reject");self.ui("C").find("rejected_reason");self.ended(c)
            for page in (a,b):page.wait_connected()
            self.record("third_call_policy","original_call_policy","new_call_policy")
        else:
            waiting.find(waiting.text_locator(self.ctx.config["lab"].get("member_names_by_viewer",{}).get(target,{}).get("C",self.ctx.config["lab"]["member_names"]["C"])))
            self.ui(target).click("end_accept");self.ended(other)
            for page in (waiting,c):page.wait_connected()
            self.record("third_call_policy","original_call_policy","new_call_policy")

    def run(self):
        for role in self.case.roles:
            self.ctx.page(role).require_idle_call()
        for requirement in self.case.requirements:
            if requirement.startswith("probe:"):
                name=requirement.split(":",1)[1]
                measure(self.ctx,name,phase="prepare",case_id=self.case.id,marker=self.marker)
                self.ctx.suite_cleanup.append(lambda n=name:measure(self.ctx,n,phase="cleanup",case_id=self.case.id,marker=self.marker))
        flow=self.p["flow"]
        if flow=="call":self.call()
        elif flow=="third_call":self.third_call()
        elif flow in ("notification","notification_clear","unread","unread_banner","inapp_notification"):self.notification()
        elif flow in ("cache","text","offline_send","draft_send","last_message","typing","forward","edit","delete","pin_message","search_message","reaction"):self.chat()
        else:
            from .rich_flows import run_rich
            run_rich(self)
        return self.finish()


def execute(ctx,case):
    preflight(ctx.config,case)
    return FullRun(ctx,case).run()
