import { useEffect, useState } from "react";
import {
  clearFaceTemplate,
  clearFaceDiagnostics,
  getDeviceConfig,
  getDeviceInfo,
  getIdentityStatus,
  getRegisteredFaces,
  isAndroidBridgeAvailable,
  isFaceDetectionAvailable,
  isIdentityVerificationAvailable,
  importFacePhotos,
  removeFaceTemplate,
  reloadSeatPage,
  provisionDeviceConfig,
  setFaceDiagnosticsEnabled,
  setVerificationThreshold,
  startFaceEnrollment,
  startFaceDetection,
  startIdentityVerification,
  stopFaceDetection,
  stopIdentityVerification,
} from "./androidBridge";
import {
  buildProvisioningPayload,
  isConfigurationVisible,
  seatAlias,
  usesAdvancedEndpoints,
} from "./configWorkflow";
import {
  buildFacePhotoPayload,
  validateFacePhotoFiles,
} from "./facePhotoImport";

const INITIAL_STATUS = {
  bridgeReady: false,
  camera: "空闲",
  face: "未检测",
  processingTime: "—",
  identity: "未注册",
  identityPerson: "—",
  enrollmentProgress: "0 / 10",
  captureStage: "—",
  registeredCount: 0,
  registeredPeople: [],
  similarity: "—",
  top2: "—",
  margin: "—",
  identityTime: "—",
  threshold: null,
  thresholdStatus: "CALIBRATION_PENDING",
  verificationLevel: "NONE",
  modelVersion: "—",
  diagnosticsEnabled: false,
  error: "无",
};

export default function App() {
  const [status, setStatus] = useState(INITIAL_STATUS);
  const [personId, setPersonId] = useState("seat-01");
  const [thresholdInput, setThresholdInput] = useState("");
  const [device, setDevice] = useState({
    deviceId: "未配置",
    seatId: null,
    seatAlias: null,
    serverBaseUrl: null,
    frontendBaseUrl: null,
    deviceTokenConfigured: false,
    manufacturer: "—",
    model: "—",
    androidVersion: "—",
    maintenancePinConfigured: false,
  });
  const [deviceConfig, setDeviceConfig] = useState({
    seatId: 1,
    centralHost: "192.168.1.10",
    serverBaseUrl: "",
    frontendBaseUrl: "",
    provisioningToken: "",
    maintenancePin: "",
    replaceExisting: false,
  });
  const [showAdvancedUrls, setShowAdvancedUrls] = useState(false);
  const [provisioning, setProvisioning] = useState(false);
  const [replacementRequired, setReplacementRequired] = useState(false);
  const [selectedFacePhotos, setSelectedFacePhotos] = useState([]);
  const [photoImporting, setPhotoImporting] = useState(false);
  const [photoImportResult, setPhotoImportResult] = useState(null);
  const diagnosticMode =
    new URLSearchParams(window.location.search).get("mode") ?? "diagnostic";
  const diagnosticMessage = {
    setup: "请先保存设备配置，正式会议界面由中央主机 /seat/{seatId} 提供。",
    checking: "正在检查中央后端健康状态，请稍候。",
    offline: "无法连接中央后端，请检查网络或配置后重试。",
    "server-error": "中央后端或会议页面返回错误，请检查服务状态后重试。",
    "binding-error": "本机设备身份、席位或版本未通过中央主机校验，已阻止加载会议页面。",
    timeout: "会议页面加载超时，请检查网络、前端服务和配置后重试。",
    maintenance: "已进入管理员维护模式；会议页面和录音已暂停。",
    diagnostic: "正式会议界面由中央主机 /seat/{seatId} 提供。",
  }[diagnosticMode] ?? "正式会议界面由中央主机 /seat/{seatId} 提供。";

  useEffect(() => {
    setStatus((current) => ({
      ...current,
      bridgeReady: isAndroidBridgeAvailable(),
    }));

    const onNativeEvent = (nativeEvent) => {
      try {
        handleAndroidEvent(nativeEvent.detail);
      } catch (error) {
        setStatus((current) => ({
          ...current,
          error: `UNKNOWN_ERROR：事件解析失败：${error.message}`,
        }));
      }
    };
    window.addEventListener("smartdesk-native-event", onNativeEvent);

    if (isAndroidBridgeAvailable()) {
      try {
        handleAndroidEvent(getDeviceInfo());
        handleAndroidEvent(getDeviceConfig());
      } catch {
        // Configuration errors are surfaced when the user saves the form.
      }
    }

    if (isIdentityVerificationAvailable()) {
      try {
        handleAndroidEvent(getIdentityStatus());
        handleAndroidEvent(getRegisteredFaces());
      } catch {
        // Model initialization errors are shown when an identity action is used.
      }
    }

    return () => {
      window.removeEventListener(
        "smartdesk-native-event",
        onNativeEvent,
      );
    };
  }, []);

  function handleAndroidEvent(event) {
    if (event?.type === "device_info") {
      setDevice(event.data);
      if (event.data.configured) {
        setShowAdvancedUrls(usesAdvancedEndpoints(event.data));
        setDeviceConfig({
          seatId: event.data.seatId,
          centralHost: event.data.centralHost ?? "",
          serverBaseUrl:
            event.data.serverBaseUrl ?? event.data.serverUrl,
          frontendBaseUrl:
            event.data.frontendBaseUrl ?? event.data.frontendUrl,
          provisioningToken: "",
          maintenancePin: "",
          replaceExisting: false,
        });
      }
      setStatus((current) => ({
        ...current,
        bridgeReady: Boolean(event.data.bridgeReady),
        error: "无",
      }));
      return;
    }

    if (event?.type === "device_config" && event.data) {
      if (event.data.centralHost) {
        setShowAdvancedUrls(usesAdvancedEndpoints(event.data));
      }
      setDeviceConfig((current) => ({
        ...current,
        ...event.data,
        provisioningToken: "",
        maintenancePin: "",
        replaceExisting: false,
      }));
      return;
    }

    if (event?.type === "device_config_saved") {
      setDeviceConfig((current) => ({
        ...current,
        ...event.data,
        provisioningToken: "",
        maintenancePin: "",
        replaceExisting: false,
      }));
      setDevice((current) => ({
        ...current,
        ...event.data,
        configured: true,
      }));
      setStatus((current) => ({
        ...current,
        error: "无",
      }));
      setProvisioning(false);
      setReplacementRequired(false);
      return;
    }

    if (event?.type === "device_provisioning_started") {
      setProvisioning(true);
      setStatus((current) => ({ ...current, error: "无" }));
      return;
    }

    if (event?.type === "face_detection_status") {
      const labels = {
        IDLE: "未检测",
        NO_FACE: "未发现人脸",
        ONE_FACE: "发现 1 张人脸",
        MULTIPLE_FACES: "发现多张人脸",
      };
      setStatus((current) => ({
        ...current,
        camera: event.data.status === "IDLE" ? "空闲" : "运行中",
        face: labels[event.data.status] ?? event.data.status,
        processingTime:
          event.data.processingTimeMs == null
            ? current.processingTime
            : `${event.data.processingTimeMs} ms`,
        error: "无",
      }));
      return;
    }

    if (event?.type === "registered_people") {
      setStatus((current) => ({
        ...current,
        registeredPeople: event.data.personIds ?? [],
        registeredCount: Number(event.data.count ?? 0),
      }));
      return;
    }

    if (event?.type === "camera_status") {
      const cameraLabels = {
        IDLE: "空闲",
        CAMERA_STARTING: "启动中",
        CAMERA_RUNNING: "运行中",
        CAMERA_STOPPING: "停止中",
      };
      setStatus((current) => ({
        ...current,
        camera: cameraLabels[event.data.status] ?? event.data.status,
        face:
          event.data.status === "CAMERA_RUNNING"
            ? "等待人脸检测模块"
            : event.data.status === "IDLE"
              ? "未检测"
              : current.face,
        processingTime:
          event.data.status === "IDLE" ? "—" : current.processingTime,
        error: "无",
      }));
      return;
    }

    if (event?.type === "identity_status") {
      const labels = {
        NOT_ENROLLED: "未注册",
        ENROLLING: "正在注册",
        ENROLLED: "已注册",
        VERIFYING: "验证中",
        VERIFIED: "验证通过",
        UNKNOWN: "未知人员",
        RETRY_REQUIRED: "需要重新验证",
        CALIBRATION_PENDING: "正在记录标定分数",
        WAITING_FOR_FACE: "等待圆圈内人脸",
        MULTIPLE_FACES: "圆圈内存在多人",
        ERROR: "处理失败",
      };
      setStatus((current) => ({
        ...current,
        identity: labels[event.data.status] ?? event.data.status,
        identityPerson: event.data.personId ?? "—",
        enrollmentProgress:
          `${event.data.sampleCount ?? 0} / ${event.data.requiredSamples ?? 10}`,
        captureStage: formatCaptureStage(event.data.captureStage),
        registeredCount: Number(event.data.registeredCount ?? 0),
        similarity:
          event.data.similarity == null
            ? "—"
            : Number(event.data.similarity).toFixed(3),
        top2:
          event.data.top2Score == null
            ? "—"
            : `${event.data.top2PersonId}：${Number(event.data.top2Score).toFixed(3)}`,
        margin:
          event.data.margin == null
            ? "—"
            : Number(event.data.margin).toFixed(3),
        identityTime:
          event.data.processingTimeMs == null
            ? current.identityTime
            : `${event.data.processingTimeMs} ms`,
        threshold:
          event.data.threshold == null
            ? null
            : Number(event.data.threshold),
        thresholdStatus:
          event.data.thresholdStatus ?? "CALIBRATION_PENDING",
        verificationLevel:
          event.data.verificationLevel ?? "NONE",
        modelVersion: event.data.modelVersion ?? "—",
        error: event.data.status === "ERROR" ? event.data.message : "无",
      }));
      if (event.data.threshold != null) {
        setThresholdInput(Number(event.data.threshold).toFixed(3));
      }
      return;
    }

    if (event?.type === "face_photo_import_result") {
      setPhotoImportResult(event.data);
      setStatus((current) => ({
        ...current,
        identity: event.data.saved ? "已注册" : current.identity,
        identityPerson: event.data.personId ?? current.identityPerson,
        registeredPeople: event.data.registeredPeople ?? [],
        registeredCount: Number(event.data.registeredPeople?.length ?? 0),
        error: event.data.saved ? "无" : event.data.message,
      }));
      return;
    }

    if (event?.type === "error") {
      setProvisioning(false);
      if (event.data.code === "DEVICE_SEAT_ALREADY_BOUND") {
        setReplacementRequired(true);
      }
      setStatus((current) => ({
        ...current,
        camera: event.data.cameraStillRunning ? current.camera : "空闲",
        error: `${event.data.code}：${event.data.message}`,
      }));
    }
  }

  function testBridge() {
    try {
      handleAndroidEvent(getDeviceInfo());
    } catch (error) {
      setStatus((current) => ({
        ...current,
        bridgeReady: false,
        error: `BRIDGE_UNAVAILABLE：${error.message}`,
      }));
    }
  }

  function updateDeviceConfig(field, value) {
    setDeviceConfig((current) => ({
      ...current,
      [field]: value,
    }));
  }

  function persistDeviceConfig(event) {
    event.preventDefault();
    const seatId = Number(deviceConfig.seatId);
    const alias = seatAlias(seatId);
    if (
      !window.confirm(
        `确认绑定本机？\n设备：${device.deviceId}\n席位：${seatId}\n别名：${alias}`,
      )
    ) {
      return;
    }

    try {
      const result = provisionDeviceConfig(
        buildProvisioningPayload(
          deviceConfig,
          device,
          showAdvancedUrls,
        ),
      );
      handleAndroidEvent(result);
    } catch (error) {
      setStatus((current) => ({
        ...current,
        error: `DEVICE_CONFIG_INVALID：${error.message}`,
      }));
    }
  }

  function openSeatPage() {
    try {
      reloadSeatPage();
    } catch (error) {
      setStatus((current) => ({
        ...current,
        error: `BRIDGE_UNAVAILABLE：${error.message}`,
      }));
    }
  }

  function startCamera() {
    try {
      setStatus((current) => ({
        ...current,
        camera: "启动中",
        error: "无",
      }));
      startFaceDetection();
    } catch (error) {
      setStatus((current) => ({
        ...current,
        camera: "空闲",
        error: error.message,
      }));
    }
  }

  function stopCamera() {
    stopFaceDetection();
  }

  function runIdentityAction(action) {
    try {
      const event = action();
      if (event) {
        handleAndroidEvent(event);
        if (event.type === "identity_status") {
          try {
            handleAndroidEvent(getRegisteredFaces());
          } catch {
            // Browser-only preview has no native template registry.
          }
        }
      }
    } catch (error) {
      setStatus((current) => ({
        ...current,
        error: `IDENTITY_ACTION_FAILED：${error.message}`,
      }));
    }
  }

  function enrollFace() {
    runIdentityAction(() => startFaceEnrollment(personId));
  }

  function verifyIdentity() {
    runIdentityAction(startIdentityVerification);
  }

  function stopIdentity() {
    runIdentityAction(stopIdentityVerification);
  }

  function clearTemplate() {
    runIdentityAction(clearFaceTemplate);
  }

  function removeTemplate() {
    runIdentityAction(() => removeFaceTemplate(personId));
  }

  function selectFacePhotos(event) {
    try {
      const files = validateFacePhotoFiles(event.target.files);
      setSelectedFacePhotos(files);
      setPhotoImportResult(null);
      setStatus((current) => ({ ...current, error: "无" }));
    } catch (error) {
      setSelectedFacePhotos([]);
      setPhotoImportResult(null);
      event.target.value = "";
      setStatus((current) => ({
        ...current,
        error: `FACE_PHOTO_SELECTION_INVALID：${error.message}`,
      }));
    }
  }

  async function importSelectedFacePhotos() {
    setPhotoImporting(true);
    setPhotoImportResult(null);
    setStatus((current) => ({ ...current, error: "无" }));
    try {
      const photos = await buildFacePhotoPayload(selectedFacePhotos);
      await new Promise((resolve) => setTimeout(resolve, 0));
      const event = importFacePhotos(personId, photos);
      handleAndroidEvent(event);
    } catch (error) {
      setStatus((current) => ({
        ...current,
        error: `FACE_PHOTO_IMPORT_FAILED：${error.message}`,
      }));
    } finally {
      setPhotoImporting(false);
    }
  }

  function applyThreshold() {
    const value = Number(thresholdInput);
    if (!Number.isFinite(value) || value < 0 || value > 1) {
      setStatus((current) => ({
        ...current,
        error: "THRESHOLD_INVALID：请输入0到1之间的原型阈值",
      }));
      return;
    }
    runIdentityAction(() => setVerificationThreshold(value));
  }

  function toggleDiagnostics() {
    const next = !status.diagnosticsEnabled;
    runIdentityAction(() => setFaceDiagnosticsEnabled(next));
    setStatus((current) => ({
      ...current,
      diagnosticsEnabled: next,
    }));
  }

  function clearDiagnostics() {
    runIdentityAction(clearFaceDiagnostics);
  }

  const cameraImplemented = isFaceDetectionAvailable();
  const identityImplemented = isIdentityVerificationAvailable();
  const cameraRunning = status.camera !== "空闲";
  const thresholdLabel =
    status.threshold == null ? "待标定" : status.threshold.toFixed(3);
  const configurationVisible = isConfigurationVisible(diagnosticMode);
  const selectedSeatAlias = seatAlias(deviceConfig.seatId);

  return (
    <main className="app-shell">
      <section className="hero">
        <span className="eyebrow">SMART DESK · ANDROID DIAGNOSTICS</span>
        <h1>平板配置与原生能力诊断</h1>
        <p>{diagnosticMessage}</p>
      </section>

      {configurationVisible && <form
        className="configuration"
        aria-label="设备配置"
        onSubmit={persistDeviceConfig}
      >
        <h2>{diagnosticMode === "setup" ? "首次设备预配" : "管理员设备维护"}</h2>
        <p className="configuration-summary">
          物理设备 ID：<strong>{device.deviceId}</strong><br />
          目标席位别名：<strong>{selectedSeatAlias}</strong>
        </p>
        <div className="configuration-grid">
          <label>
            <span>席位编号（1–9）</span>
            <input
              type="number"
              min="1"
              max="9"
              required
              value={deviceConfig.seatId}
              onChange={(event) =>
                updateDeviceConfig("seatId", event.target.value)
              }
            />
          </label>
          <label>
            <span>中央主机 IP 或主机名</span>
            <input
              required
              value={deviceConfig.centralHost}
              onChange={(event) =>
                updateDeviceConfig("centralHost", event.target.value)
              }
            />
          </label>
          <label>
            <span>服务器预配口令</span>
            <input
              type="password"
              required
              minLength="24"
              maxLength="256"
              autoComplete="new-password"
              value={deviceConfig.provisioningToken}
              onChange={(event) =>
                updateDeviceConfig("provisioningToken", event.target.value)
              }
            />
          </label>
          {!device.maintenancePinConfigured && <label>
            <span>本地维护 PIN（6–12 位数字）</span>
            <input
              type="password"
              inputMode="numeric"
              pattern="[0-9]{6,12}"
              required
              minLength="6"
              maxLength="12"
              autoComplete="new-password"
              value={deviceConfig.maintenancePin}
              onChange={(event) =>
                updateDeviceConfig("maintenancePin", event.target.value)
              }
            />
          </label>}
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={showAdvancedUrls}
              onChange={(event) =>
                setShowAdvancedUrls(event.target.checked)
              }
            />
            <span>高级：覆盖后端与前端 URL</span>
          </label>
          {showAdvancedUrls && <>
            <label>
              <span>业务后端地址</span>
              <input
                type="url"
                required
                placeholder="http://192.168.1.10:8000"
                value={deviceConfig.serverBaseUrl}
                onChange={(event) =>
                  updateDeviceConfig("serverBaseUrl", event.target.value)
                }
              />
            </label>
            <label>
              <span>会议前端地址</span>
              <input
                type="url"
                required
                placeholder="http://192.168.1.10:5173"
                value={deviceConfig.frontendBaseUrl}
                onChange={(event) =>
                  updateDeviceConfig("frontendBaseUrl", event.target.value)
                }
              />
            </label>
          </>}
        </div>
        {replacementRequired && <label className="replacement-confirmation">
          <input
            type="checkbox"
            checked={deviceConfig.replaceExisting}
            onChange={(event) =>
              updateDeviceConfig("replaceExisting", event.target.checked)
            }
          />
          <span>目标席位已绑定其他平板；确认解除旧绑定并由本机替换</span>
        </label>}
        <div className="configuration-actions">
          <button
            type="submit"
            className="primary"
            disabled={provisioning || (replacementRequired && !deviceConfig.replaceExisting)}
          >
            {provisioning ? "正在绑定中央主机…" : "绑定并打开正式席位页面"}
          </button>
          <button type="button" onClick={openSeatPage}>
            使用已保存配置重试
          </button>
        </div>
      </form>}

      {!configurationVisible && <div className="configuration-actions status-actions">
        <button type="button" onClick={openSeatPage}>
          重新检查并打开席位页面
        </button>
      </div>}

      <section className="panel" aria-label="设备和检测状态">
        <div className="status-row">
          <span>设备编号</span>
          <strong>{device.deviceId}</strong>
        </div>
        <div className="status-row">
          <span>绑定席位</span>
          <strong>
            {device.seatId == null
              ? "未配置"
              : `${device.seatId} · ${device.seatAlias ?? seatAlias(device.seatId)}`}
          </strong>
        </div>
        <div className="status-row">
          <span>设备型号</span>
          <strong>
            {device.manufacturer} {device.model}
          </strong>
        </div>
        <div className="status-row">
          <span>Android 版本</span>
          <strong>{device.androidVersion}</strong>
        </div>
        <div className="status-row">
          <span>Android Bridge</span>
          <strong className={status.bridgeReady ? "ok" : "muted"}>
            {status.bridgeReady ? "已连接" : "未连接"}
          </strong>
        </div>
        <div className="status-row">
          <span>摄像头</span>
          <strong>{status.camera}</strong>
        </div>
        <div className="status-row">
          <span>人脸状态</span>
          <strong>{status.face}</strong>
        </div>
        <div className="status-row">
          <span>检测耗时</span>
          <strong>{status.processingTime}</strong>
        </div>
        <div className="status-row">
          <span>已注册人员</span>
          <strong>
            {status.registeredCount} / 9
            {status.registeredPeople.length > 0
              ? `（${status.registeredPeople.join("、")}）`
              : ""}
          </strong>
        </div>
        <div className="status-row">
          <span>身份状态</span>
          <strong className={status.identity === "验证通过" ? "ok" : ""}>
            {status.identity}
          </strong>
        </div>
        <div className="status-row">
          <span>采集阶段</span>
          <strong>{status.captureStage}</strong>
        </div>
        <div className="status-row">
          <span>模板人员</span>
          <strong>{status.identityPerson}</strong>
        </div>
        <div className="status-row">
          <span>注册进度</span>
          <strong>{status.enrollmentProgress}</strong>
        </div>
        <div className="status-row">
          <span>Top1 / 阈值</span>
          <strong>
            {status.identityPerson}：{status.similarity} / {thresholdLabel}
          </strong>
        </div>
        <div className="status-row">
          <span>Top2 / 分差</span>
          <strong>
            {status.top2} / {status.margin}
          </strong>
        </div>
        <div className="status-row">
          <span>阈值状态</span>
          <strong>
            {status.thresholdStatus} · {status.verificationLevel}
          </strong>
        </div>
        <div className="status-row">
          <span>模型版本</span>
          <strong>{status.modelVersion}</strong>
        </div>
        <div className="status-row">
          <span>对齐与推理耗时</span>
          <strong>{status.identityTime}</strong>
        </div>
        <div className="status-row error-row">
          <span>错误信息</span>
          <strong className={status.error === "无" ? "muted" : "error"}>
            {status.error}
          </strong>
        </div>
      </section>

      <section className="actions" aria-label="测试操作">
        <button type="button" className="primary" onClick={testBridge}>
          测试 Android 通信
        </button>
        <button
          type="button"
          onClick={startCamera}
          disabled={!cameraImplemented || cameraRunning}
        >
          打开摄像头
        </button>
        <button
          type="button"
          onClick={stopCamera}
          disabled={!cameraImplemented || !cameraRunning}
        >
          停止检测
        </button>
      </section>

      {diagnosticMode === "maintenance" && <section
        className="photo-import"
        aria-label="上传参会者照片"
      >
        <h2>上传参会者照片</h2>
        <p>
          填写人员编号后选择 5–20 张清晰的 JPG/PNG 正脸照片。
          原图不会保存，只保留加密人脸特征。
        </p>
        <label>
          <span>参会者编号</span>
          <input
            value={personId}
            maxLength={64}
            onChange={(event) => setPersonId(event.target.value)}
          />
        </label>
        <label>
          <span>选择照片（可多选）</span>
          <input
            type="file"
            accept="image/jpeg,image/png"
            multiple
            disabled={photoImporting || cameraRunning}
            onChange={selectFacePhotos}
          />
        </label>
        <div className="photo-import-summary">
          已选择：<strong>{selectedFacePhotos.length}</strong> 张
        </div>
        <button
          type="button"
          className="primary"
          disabled={
            !identityImplemented ||
            photoImporting ||
            cameraRunning ||
            selectedFacePhotos.length < 5
          }
          onClick={importSelectedFacePhotos}
        >
          {photoImporting ? "正在检查并生成模板…" : "导入为当前人员模板"}
        </button>
        {photoImportResult && <div
          className={photoImportResult.saved ? "import-result ok" : "import-result error"}
        >
          <strong>{photoImportResult.message}</strong>
          <span>
            合格 {photoImportResult.acceptedCount} / 已选 {photoImportResult.selectedCount}；
            用于模板 {photoImportResult.usedCount} 张
          </span>
          {photoImportResult.rejected?.length > 0 && <ul>
            {photoImportResult.rejected.map((item) => <li key={item.name}>
              {item.name}：{item.reason}
            </li>)}
          </ul>}
        </div>}
      </section>}

      <section className="identity-controls" aria-label="人脸身份验证">
        <label>
          <span>座位人员编号</span>
          <input
            value={personId}
            maxLength={64}
            onChange={(event) => setPersonId(event.target.value)}
          />
        </label>
        <div className="identity-actions">
          <button
            type="button"
            className="primary"
            disabled={!identityImplemented || cameraRunning}
            onClick={enrollFace}
          >
            注册双光照 5+5 帧
          </button>
          <button
            type="button"
            disabled={
              !identityImplemented ||
              cameraRunning ||
              status.registeredCount < 2
            }
            onClick={verifyIdentity}
          >
            开始身份验证
          </button>
          <button
            type="button"
            disabled={!identityImplemented || !cameraRunning}
            onClick={stopIdentity}
          >
            停止身份验证
          </button>
          <button
            type="button"
            disabled={!identityImplemented || cameraRunning}
            onClick={clearTemplate}
          >
            清除模板
          </button>
          <button
            type="button"
            disabled={!identityImplemented || cameraRunning}
            onClick={removeTemplate}
          >
            删除当前编号
          </button>
        </div>
        <div className="threshold-control">
          <label>
            <span>原型标定阈值（0–1）</span>
            <input
              type="number"
              min="0"
              max="1"
              step="0.001"
              value={thresholdInput}
              onChange={(event) => setThresholdInput(event.target.value)}
            />
          </label>
          <button
            type="button"
            disabled={
              !identityImplemented ||
              cameraRunning ||
              status.registeredCount < 2
            }
            onClick={applyThreshold}
          >
            应用 PROVISIONAL 阈值
          </button>
        </div>
        <div className="identity-actions">
          <button
            type="button"
            disabled={!identityImplemented || cameraRunning}
            onClick={toggleDiagnostics}
          >
            {status.diagnosticsEnabled
              ? "关闭 Debug 诊断"
              : "开启 Debug 诊断"}
          </button>
          <button
            type="button"
            disabled={!identityImplemented || cameraRunning}
            onClick={clearDiagnostics}
          >
            清除诊断数据
          </button>
        </div>
      </section>

      <p className="phase-note">
        {identityImplemented
          ? "本页只用于配置、注册与标定；PROVISIONAL 结果不会在这里触发会议签到。"
          : "MobileFaceNet 身份验证仅在 Android App 中可用。"}
      </p>
    </main>
  );
}

function formatCaptureStage(value) {
  const labels = {
    NONE: "—",
    NORMAL_WAITING_FOR_FACE: "自然光 · 等待人脸",
    NORMAL_METERING: "自然光 · 中央测光",
    NORMAL_STABILITY: "自然光 · 亮度稳定检查",
    NORMAL_CAPTURING: "自然光 · 采集5帧",
    FILL_LIGHT_WAITING_FOR_FACE: "屏幕补光 · 等待人脸",
    FILL_LIGHT_METERING: "屏幕补光 · 中央测光",
    FILL_LIGHT_STABILITY: "屏幕补光 · 亮度稳定检查",
    FILL_LIGHT_CAPTURING: "屏幕补光 · 采集5帧",
  };
  return labels[value] ?? value ?? "—";
}
