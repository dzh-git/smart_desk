import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowLeft, RefreshCw, ShieldCheck, Trash2, Upload } from "lucide-react";
import type { Meeting, Person } from "../api/types";
import { createPerson, fetchMeetings, fetchPeople } from "../api/resources";
import {
  deleteFaceTemplate,
  fetchFaceAssignments,
  fetchFaceTemplateLibrary,
  fetchTabletFaceSyncStatus,
  updateFaceAssignments,
  type FaceSeatAssignments,
  type FaceTemplateLibrary,
  type TabletFaceSyncStatus,
} from "../api/faceTemplates";
import { getNativeBridge } from "../native/NativeBridge";
import type { RegisteredFaces } from "../native/NativeBridge";
import type { NativeIdentityStatus } from "../native/nativeEvents";

interface Access {
  deviceId: string;
  token: string;
}

interface PhotoPayload {
  name: string;
  mimeType: string;
  base64: string;
}

const PARTICIPANT_SEATS = Array.from({ length: 8 }, (_, index) => index + 2);
const ALL_FACE_SEATS = [1, ...PARTICIPANT_SEATS];
const DEFAULT_PROTOTYPE_THRESHOLD = 0.55;

export function FaceTemplateManager() {
  const bridge = useMemo(() => getNativeBridge(), []);
  const [access, setAccess] = useState<Access | null>(null);
  const [denied, setDenied] = useState<string | null>(null);
  const [library, setLibrary] = useState<FaceTemplateLibrary | null>(null);
  const [localFaces, setLocalFaces] = useState<RegisteredFaces>({ personIds: [], count: 0 });
  const [nativeIdentityStatus, setNativeIdentityStatus] = useState<NativeIdentityStatus | null>(null);
  const [thresholdInput, setThresholdInput] = useState(DEFAULT_PROTOTYPE_THRESHOLD.toFixed(3));
  const [people, setPeople] = useState<Person[]>([]);
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [meetingId, setMeetingId] = useState<number | null>(null);
  const [assignments, setAssignments] = useState<FaceSeatAssignments | null>(null);
  const [assignmentDraft, setAssignmentDraft] = useState<Record<number, string>>(emptyAssignmentDraft);
  const [syncStatus, setSyncStatus] = useState<TabletFaceSyncStatus[]>([]);
  const [selectedPersonId, setSelectedPersonId] = useState("");
  const [newPersonName, setNewPersonName] = useState("");
  const [newPersonCode, setNewPersonCode] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadCore = useCallback(async (current: Access) => {
    const [nextLibrary, nextPeople, nextMeetings, nextSync, nextLocalFaces, nextIdentityStatus] = await Promise.all([
      fetchFaceTemplateLibrary(current.deviceId, current.token),
      fetchPeople(),
      fetchMeetings(),
      fetchTabletFaceSyncStatus(),
      bridge.getRegisteredFaces(),
      bridge.getNativeStatus(),
    ]);
    setLibrary(nextLibrary);
    setPeople(nextPeople);
    setMeetings(nextMeetings);
    setSyncStatus(nextSync);
    setLocalFaces(nextLocalFaces);
    setNativeIdentityStatus(nextIdentityStatus);
    setThresholdInput(
      typeof nextIdentityStatus.threshold === "number"
        ? nextIdentityStatus.threshold.toFixed(3)
        : DEFAULT_PROTOTYPE_THRESHOLD.toFixed(3),
    );
    setSelectedPersonId((currentPerson) => currentPerson || nextPeople[0]?.id || "__new__");
    setMeetingId((currentMeeting) => {
      if (currentMeeting && nextMeetings.some((meeting) => meeting.id === currentMeeting)) {
        return currentMeeting;
      }
      const pending = nextMeetings.filter((meeting) => meeting.status === "pending");
      return nextMeetings.find((meeting) => meeting.status === "active")?.id
        ?? pending[pending.length - 1]?.id
        ?? null;
    });
  }, [bridge]);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        if (!bridge.isAvailable()) throw new Error("仅允许从已绑定的主持人 Android 平板进入");
        const info = await bridge.getDeviceInfo();
        if (info.seatId !== 1 || !info.configured) {
          throw new Error("当前设备不是已绑定的 Seat 1 主持人平板");
        }
        const nextAccess = { deviceId: info.deviceId, token: await bridge.getDeviceCredential() };
        if (!active) return;
        setAccess(nextAccess);
        await loadCore(nextAccess);
      } catch (reason) {
        if (active) setDenied(errorMessage(reason));
      }
    })();
    return () => { active = false; };
  }, [bridge, loadCore]);

  useEffect(() => {
    if (!access || meetingId == null) {
      setAssignments(null);
      setAssignmentDraft(emptyAssignmentDraft());
      return;
    }
    let active = true;
    void fetchFaceAssignments(meetingId, access.deviceId, access.token)
      .then((result) => {
        if (!active) return;
        setAssignments(result);
        setAssignmentDraft(Object.fromEntries(
          ALL_FACE_SEATS.map((seatId) => [
            seatId,
            result.assignments.find((item) => item.seatId === seatId)?.personId ?? "",
          ]),
        ));
      })
      .catch((reason) => active && setError(errorMessage(reason)));
    return () => { active = false; };
  }, [access, meetingId]);

  async function refresh() {
    if (!access) return;
    setBusy(true);
    setError(null);
    try {
      await loadCore(access);
      if (meetingId != null) {
        const next = await fetchFaceAssignments(meetingId, access.deviceId, access.token);
        setAssignments(next);
      }
      setMessage("已刷新模板库、会议分配和各平板同步状态");
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function publishTemplate() {
    if (!access) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const photos = await buildPhotoPayload(files);
      const personId = await resolveSelectedPerson();
      const result = await bridge.publishCentralFaceTemplate(personId, JSON.stringify(photos));
      await loadCore(access);
      setMessage(`“${result.template.personName}”的人脸模板已保存，原始照片未上传服务器。`);
      if (result.evictedPersonName) {
        window.alert(`模板库已满，已自动删除最早且未被会议使用的模板：${result.evictedPersonName}`);
      }
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function saveHostTemplate() {
    if (!access) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const photos = await buildPhotoPayload(files);
      const personId = await resolveSelectedPerson();
      const result = await bridge.importLocalFaceTemplate(personId, JSON.stringify(photos));
      await loadCore(access);
      setMessage(result.message || `“${personDisplayName(personId)}”已保存为主持人本机模板`);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function confirmPrototypeThreshold() {
    const value = Number(thresholdInput);
    if (!Number.isFinite(value) || value < 0 || value > 1) {
      setError("原型阈值必须是 0 到 1 之间的数字");
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await bridge.applyProvisionalThreshold(value);
      setNativeIdentityStatus(result);
      setThresholdInput(value.toFixed(3));
      setMessage(`当前模型的原型阈值已确认为 ${value.toFixed(3)}；仅限内部验证。`);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function resolveSelectedPerson(): Promise<string> {
    let personId = selectedPersonId;
    if (selectedPersonId === "__new__") {
      const name = newPersonName.trim();
      if (!name) throw new Error("请输入新人员姓名");
      personId = newPersonCode.trim() || `person-${Date.now()}`;
      await createPerson(personId, name);
      setSelectedPersonId(personId);
    }
    if (!personId) throw new Error("请选择人员");
    return personId;
  }

  function personDisplayName(personId: string): string {
    return people.find((person) => person.id === personId)?.name ?? personId;
  }

  async function removeTemplate(personId: string, personName: string) {
    if (!access || !window.confirm(`确认删除“${personName}”的人脸模板？人员和历史会议数据会保留。`)) return;
    setBusy(true);
    setError(null);
    try {
      await deleteFaceTemplate(personId, access.deviceId, access.token);
      await loadCore(access);
      setMessage(`已删除“${personName}”的人脸模板`);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function removeLocalTemplate(personId: string) {
    if (!access || !window.confirm(`确认从主持人平板删除“${personDisplayName(personId)}”的本机模板？中央模板不会被删除。`)) return;
    setBusy(true);
    setError(null);
    try {
      await bridge.removeLocalFaceTemplate(personId);
      await loadCore(access);
      setMessage(`已从主持人平板删除“${personDisplayName(personId)}”的本机模板`);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function saveAssignments() {
    if (!access || meetingId == null) return;
    const selected = Object.values(assignmentDraft).filter(Boolean);
    if (new Set(selected).size !== selected.length) {
      setError("同一个人员不能同时分配到多个席位；本人测试时请先离席再改到下一席位");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await updateFaceAssignments(
        meetingId,
        access.deviceId,
        access.token,
        ALL_FACE_SEATS.map((seatId) => ({ seatId, personId: assignmentDraft[seatId] || null })),
      );
      setAssignments(result);
      setMessage(`席位分配已保存，会议模板集版本为 ${result.templateSetRevision}`);
      setSyncStatus(await fetchTabletFaceSyncStatus());
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  if (denied) return <AccessDenied message={denied} />;
  if (!access || !library) {
    return <div className="min-h-screen bg-slate-950 text-white grid place-items-center">正在验证主持人设备…</div>;
  }

  const editableMeetings = meetings.filter((meeting) => meeting.status !== "finished");
  const thresholdValue = Number(thresholdInput);
  const thresholdValid = Number.isFinite(thresholdValue) && thresholdValue >= 0 && thresholdValue <= 1;
  const thresholdConfirmed = nativeIdentityStatus?.thresholdStatus === "PROVISIONAL"
    && typeof nativeIdentityStatus.threshold === "number";
  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 p-5 md:p-8">
      <div className="mx-auto max-w-6xl space-y-5">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs tracking-[0.24em] text-cyan-400">SEAT 1 · MAINTENANCE</p>
            <h1 className="text-2xl font-bold">人脸模板管理</h1>
            <p className="mt-1 text-sm text-slate-400">主持人本机模板用于 Seat 1；中央模板用于分配并下发给 Seat 2–9。</p>
          </div>
          <div className="flex gap-2">
            <button className="rounded-lg border border-slate-700 px-3 py-2 text-sm" onClick={() => void bridge.openLocalDiagnostics()}>设备诊断</button>
            <button className="rounded-lg bg-slate-800 px-3 py-2 text-sm" onClick={() => void bridge.closeHostFaceTemplates()}><ArrowLeft className="mr-1 inline" size={15} />返回会议</button>
          </div>
        </header>

        {(message || error) && <div className={`rounded-xl border p-3 text-sm ${error ? "border-red-700 bg-red-950/60 text-red-200" : "border-emerald-700 bg-emerald-950/50 text-emerald-200"}`}>{error ?? message}</div>}
        {library.count === 0 && <div className="rounded-xl border border-amber-700 bg-amber-950/50 p-3 text-sm text-amber-200">中央模板库尚为空。Seat 2–9 分配一位人员并完成其模板注册后，即可进行该席位的一对一验证。</div>}

        <section className="grid gap-5 lg:grid-cols-[1fr_1.2fr]">
          <div className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
            <h2 className="font-semibold">新建或更新人脸模板</h2>
            <label className="mt-4 block text-sm text-slate-300">人员
              <select className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 p-2" value={selectedPersonId} onChange={(event) => setSelectedPersonId(event.target.value)}>
                {people.map((person) => <option key={person.id} value={person.id}>{person.name} · {person.id}</option>)}
                <option value="__new__">＋ 新建人员</option>
              </select>
            </label>
            {selectedPersonId === "__new__" && <div className="mt-3 grid grid-cols-2 gap-2">
              <input className="rounded-lg border border-slate-700 bg-slate-950 p-2" placeholder="姓名" value={newPersonName} onChange={(event) => setNewPersonName(event.target.value)} />
              <input className="rounded-lg border border-slate-700 bg-slate-950 p-2" placeholder="人员编号（可留空）" value={newPersonCode} onChange={(event) => setNewPersonCode(event.target.value)} />
            </div>}
            <label htmlFor="host-face-photo-picker" className="mt-4 block cursor-pointer rounded-xl border border-dashed border-slate-600 p-4 text-center text-sm hover:border-cyan-500">
              <Upload className="mx-auto mb-2 text-cyan-400" />
              选择 5–20 张 JPG/PNG 正脸照片
              <span className="mt-3 inline-block rounded-lg bg-slate-800 px-4 py-2 text-cyan-200">选择照片</span>
              <input id="host-face-photo-picker" className="sr-only" type="file" accept=".jpg,.jpeg,.png,image/jpeg,image/png" multiple onChange={(event) => setFiles(Array.from(event.target.files ?? []))} />
            </label>
            <p className="mt-2 text-xs text-slate-400">已选择 {files.length} 张；单张不超过 5 MB，总计不超过 50 MB。</p>
            <div className="mt-4 grid gap-2">
              <button className="w-full rounded-lg bg-emerald-600 px-4 py-2 font-medium disabled:opacity-40" disabled={busy || files.length < 5 || files.length > 20} onClick={() => void saveHostTemplate()}>{busy ? "正在处理…" : "保存为主持人本机模板（Seat 1）"}</button>
              <button className="w-full rounded-lg bg-cyan-600 px-4 py-2 font-medium disabled:opacity-40" disabled={busy || files.length < 5 || files.length > 20} onClick={() => void publishTemplate()}>{busy ? "正在处理…" : "保存到中央参会者模板库（Seat 2–9）"}</button>
            </div>
            <p className="mt-3 text-xs text-slate-500">如同一人员既是主持人又需要作为参会者测试，请用同一批照片分别点击两个保存按钮。</p>
          </div>

          <div className="space-y-5">
            <div className="rounded-2xl border border-emerald-900 bg-slate-900 p-5">
              <div className="flex items-center justify-between"><div><h2 className="font-semibold">主持人本机模板</h2><p className="mt-1 text-xs text-slate-400">仅保存在当前 Seat 1 平板，用于主持人身份验证。</p></div><span className="text-sm text-slate-400">{localFaces.count} 个</span></div>
              <div className="mt-3 max-h-40 overflow-auto divide-y divide-slate-800">
                {localFaces.personIds.length === 0 && <p className="py-6 text-center text-sm text-slate-500">尚未设置主持人本机模板</p>}
                {localFaces.personIds.map((personId) => <div key={personId} className="flex items-center justify-between gap-3 py-3">
                  <div><p className="font-medium">{personDisplayName(personId)}</p><p className="text-xs text-slate-500">{personId}</p></div>
                  <button className="inline-flex items-center gap-1 rounded-lg px-3 py-2 text-sm text-red-400 hover:bg-red-950" disabled={busy} onClick={() => void removeLocalTemplate(personId)} aria-label={`删除主持人本机模板${personDisplayName(personId)}`}><Trash2 size={16} />删除</button>
                </div>)}
              </div>
            </div>

            <div className="rounded-2xl border border-violet-900 bg-slate-900 p-5">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="font-semibold">当前模型识别阈值</h2>
                  <p className="mt-1 text-xs text-slate-400">默认值为 0.55；模型或处理流水线变化后需在这里重新确认。</p>
                </div>
                <span className={`text-sm ${thresholdConfirmed ? "text-emerald-400" : "text-amber-300"}`}>
                  {thresholdConfirmed ? "PROVISIONAL" : "待确认"}
                </span>
              </div>
              <div className="mt-4 flex flex-wrap items-end gap-3">
                <label className="min-w-44 flex-1 text-sm text-slate-300">原型识别阈值
                  <input
                    aria-label="原型识别阈值"
                    className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 p-2"
                    type="number"
                    min="0"
                    max="1"
                    step="0.001"
                    value={thresholdInput}
                    onChange={(event) => setThresholdInput(event.target.value)}
                  />
                </label>
                <button
                  className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium disabled:opacity-40"
                  disabled={busy || !thresholdValid}
                  onClick={() => void confirmPrototypeThreshold()}
                >
                  确认当前模型阈值
                </button>
              </div>
              <p className="mt-3 text-xs text-slate-400">阈值只与当前模型及处理流水线关联，不受主持人本机模板或中央模板数量影响。</p>
              <p className="mt-3 text-xs text-slate-500">该阈值仅用于当前非商业研究原型，不代表正式身份认证安全等级。</p>
            </div>

            <div className="rounded-2xl border border-cyan-900 bg-slate-900 p-5">
              <div className="flex items-center justify-between"><div><h2 className="font-semibold">中央参会者模板库</h2><p className="mt-1 text-xs text-slate-400">这里的人员才会出现在 Seat 2–9 分配下拉框。</p></div><span className="text-sm text-slate-400">{library.count} / {library.capacity}</span></div>
              <div className="mt-3 max-h-48 overflow-auto divide-y divide-slate-800">
                {library.templates.length === 0 && <p className="py-6 text-center text-sm text-slate-500">尚未注册中央模板</p>}
                {library.templates.map((template) => <div key={template.personId} className="flex items-center justify-between gap-3 py-3">
                  <div><p className="font-medium">{template.personName}</p><p className="text-xs text-slate-500">{template.personId} · rev {template.revision} · pipeline {template.pipelineVersion}</p></div>
                  <button className="inline-flex items-center gap-1 rounded-lg px-3 py-2 text-sm text-red-400 hover:bg-red-950" disabled={busy} onClick={() => void removeTemplate(template.personId, template.personName)} aria-label={`删除中央模板${template.personName}`}><Trash2 size={16} />删除</button>
                </div>)}
              </div>
              <p className="mt-2 text-xs text-slate-500">正在被待开始或进行中会议使用的中央模板，需先解除席位分配后才能删除。</p>
            </div>
          </div>
        </section>

        <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div><h2 className="font-semibold">Seat 2–9 会议分配</h2><p className="text-xs text-slate-400">本人依次测试时，先在当前席位离席，再将同一人员改到下一席位。</p></div>
            <select className="rounded-lg border border-slate-700 bg-slate-950 p-2 text-sm" value={meetingId ?? ""} onChange={(event) => setMeetingId(event.target.value ? Number(event.target.value) : null)}>
              <option value="">选择待开始或进行中的会议</option>
              {editableMeetings.map((meeting) => <option key={meeting.id} value={meeting.id}>{meeting.title} · {meeting.status}</option>)}
            </select>
          </div>
          <div className="mt-4 rounded-xl border border-emerald-800 bg-emerald-950/20 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="font-semibold text-emerald-200">Seat 1 · 本场主持人</h3>
                <p className="mt-1 text-xs text-slate-400">仅使用主持人平板本机模板，返回席位页后按指定人员进行 1:1 验证。</p>
              </div>
              <select
                aria-label="Seat 1 本场主持人"
                className="min-w-56 rounded-lg border border-emerald-800 bg-slate-950 p-2 text-sm"
                disabled={meetingId == null}
                value={assignmentDraft[1] ?? ""}
                onChange={(event) => setAssignmentDraft((draft) => ({ ...draft, 1: event.target.value }))}
              >
                <option value="">未分配</option>
                {localFaces.personIds.map((personId) => <option key={personId} value={personId}>{personDisplayName(personId)}</option>)}
              </select>
            </div>
            {localFaces.count === 0 && <p className="mt-3 text-xs text-amber-300">尚未注册主持人本机模板，无法分配 Seat 1。</p>}
          </div>
          <h3 className="mt-5 text-sm font-semibold text-cyan-200">Seat 2–9 · 中央参会者模板</h3>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {PARTICIPANT_SEATS.map((seatId) => <label key={seatId} className="rounded-xl border border-slate-800 bg-slate-950 p-3 text-sm">Seat {seatId}
              <select className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-900 p-2" disabled={meetingId == null} value={assignmentDraft[seatId] ?? ""} onChange={(event) => setAssignmentDraft((draft) => ({ ...draft, [seatId]: event.target.value }))}>
                <option value="">未分配</option>
                {library.templates.map((template) => <option key={template.personId} value={template.personId}>{template.personName}</option>)}
              </select>
            </label>)}
          </div>
          <button className="mt-4 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium disabled:opacity-40" disabled={busy || meetingId == null} onClick={() => void saveAssignments()}>保存席位分配</button>
          {assignments && <span className="ml-3 text-xs text-slate-500">模板集版本 {assignments.templateSetRevision}</span>}
        </section>

        <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
          <div className="flex justify-between"><h2 className="font-semibold">参会者平板同步状态</h2><button className="text-slate-400" onClick={() => void refresh()} aria-label="刷新"><RefreshCw size={17} /></button></div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {syncStatus.map((tablet) => <div key={tablet.seat_id} className="rounded-xl border border-slate-800 bg-slate-950 p-3 text-sm">
              <div className="flex justify-between"><strong>Seat {tablet.seat_id}</strong><span className={tablet.online ? "text-emerald-400" : "text-slate-500"}>{tablet.online ? "在线" : "离线"}</span></div>
              <p className="mt-2 text-xs text-slate-400">{tablet.face_template_sync_status ?? "尚未同步"} · {tablet.face_template_sync_count ?? 0} 个</p>
              <p className="text-xs text-slate-500">会议 {tablet.face_template_meeting_id ?? "—"} · 版本 {tablet.face_template_set_revision ?? "—"}</p>
              {tablet.face_template_sync_error && <p className="mt-1 text-xs text-red-400">{tablet.face_template_sync_error}</p>}
            </div>)}
          </div>
        </section>
      </div>
    </main>
  );
}

function emptyAssignmentDraft(): Record<number, string> {
  return Object.fromEntries(ALL_FACE_SEATS.map((seatId) => [seatId, ""]));
}

async function buildPhotoPayload(files: File[]): Promise<PhotoPayload[]> {
  if (files.length < 5 || files.length > 20) throw new Error("请选择 5–20 张照片");
  let total = 0;
  for (const file of files) {
    if (!["image/jpeg", "image/png"].includes(file.type)) throw new Error(`${file.name}：只支持 JPG 或 PNG`);
    if (file.size === 0 || file.size > 5 * 1024 * 1024) throw new Error(`${file.name}：单张照片不得超过 5 MB`);
    total += file.size;
  }
  if (total > 50 * 1024 * 1024) throw new Error("照片总大小不得超过 50 MB");
  return Promise.all(files.map(async (file) => ({
    name: file.name,
    mimeType: file.type,
    base64: arrayBufferToBase64(await file.arrayBuffer()),
  })));
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunk = 0x8000;
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
  }
  return btoa(binary);
}

function errorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

function AccessDenied({ message }: { message: string }) {
  return <main className="min-h-screen bg-slate-950 text-slate-100 grid place-items-center p-6"><div className="max-w-md rounded-2xl border border-red-800 bg-red-950/40 p-6 text-center"><AlertTriangle className="mx-auto text-red-400" /><h1 className="mt-3 text-xl font-bold">禁止访问</h1><p className="mt-2 text-sm text-red-200">{message}</p><p className="mt-4 text-xs text-slate-400"><ShieldCheck className="mr-1 inline" size={14} />请在 Seat 1 平板长按右上角图标 5 秒并验证维护 PIN。</p></div></main>;
}
