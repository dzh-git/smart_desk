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
  removeFaceTemplate,
  reloadSeatPage,
  saveDeviceConfig,
  setFaceDiagnosticsEnabled,
  setVerificationThreshold,
  startFaceEnrollment,
  startFaceDetection,
  startIdentityVerification,
  stopFaceDetection,
  stopIdentityVerification,
} from "./androidBridge";

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
    serverUrl: null,
    frontendUrl: null,
    manufacturer: "—",
    model: "—",
    androidVersion: "—",
  });
  const [deviceConfig, setDeviceConfig] = useState({
    seatId: 1,
    deviceId: "",
    serverUrl: "http://192.168.1.10:8000",
    frontendUrl: "http://192.168.1.10:5173",
  });
  const diagnosticMode =
    new URLSearchParams(window.location.search).get("mode") ?? "diagnostic";

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
        setDeviceConfig({
          seatId: event.data.seatId,
          deviceId: event.data.deviceId,
          serverUrl: event.data.serverUrl,
          frontendUrl: event.data.frontendUrl,
        });
      } else {
        setDeviceConfig((current) => ({
          ...current,
          deviceId: event.data.deviceId,
        }));
      }
      setStatus((current) => ({
        ...current,
        bridgeReady: Boolean(event.data.bridgeReady),
        error: "无",
      }));
      return;
    }

    if (event?.type === "device_config" && event.data) {
      setDeviceConfig(event.data);
      return;
    }

    if (event?.type === "device_config_saved") {
      setDeviceConfig(event.data);
      setDevice((current) => ({
        ...current,
        ...event.data,
        configured: true,
      }));
      setStatus((current) => ({
        ...current,
        error: "无",
      }));
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

    if (event?.type === "error") {
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
    try {
      const result = saveDeviceConfig({
        ...deviceConfig,
        seatId: Number(deviceConfig.seatId),
      });
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

  return (
    <main className="app-shell">
      <section className="hero">
        <span className="eyebrow">SMART DESK · ANDROID DIAGNOSTICS</span>
        <h1>平板配置与原生能力诊断</h1>
        <p>
          {diagnosticMode === "offline"
            ? "中央会议页面暂时不可用，请检查网络或配置后重试。"
            : "正式会议界面由中央主机 /seat/{seatId} 提供。"}
        </p>
      </section>

      <form
        className="configuration"
        aria-label="设备配置"
        onSubmit={persistDeviceConfig}
      >
        <h2>设备配置</h2>
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
            <span>设备编号</span>
            <input
              required
              minLength="3"
              maxLength="64"
              pattern="[A-Za-z0-9._-]+"
              value={deviceConfig.deviceId}
              onChange={(event) =>
                updateDeviceConfig("deviceId", event.target.value)
              }
            />
          </label>
          <label>
            <span>业务后端地址</span>
            <input
              type="url"
              required
              value={deviceConfig.serverUrl}
              onChange={(event) =>
                updateDeviceConfig("serverUrl", event.target.value)
              }
            />
          </label>
          <label>
            <span>会议前端地址</span>
            <input
              type="url"
              required
              value={deviceConfig.frontendUrl}
              onChange={(event) =>
                updateDeviceConfig("frontendUrl", event.target.value)
              }
            />
          </label>
        </div>
        <div className="configuration-actions">
          <button type="submit" className="primary">
            保存并打开正式席位页面
          </button>
          <button type="button" onClick={openSeatPage}>
            使用已保存配置重试
          </button>
        </div>
      </form>

      <section className="panel" aria-label="设备和检测状态">
        <div className="status-row">
          <span>设备编号</span>
          <strong>{device.deviceId}</strong>
        </div>
        <div className="status-row">
          <span>绑定席位</span>
          <strong>{device.seatId ?? "未配置"}</strong>
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
