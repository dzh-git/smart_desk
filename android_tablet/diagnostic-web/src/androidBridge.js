function requireAndroidBridge() {
  if (!window.SmartDeskNative) {
    throw new Error("SmartDeskNative Bridge unavailable");
  }

  return window.SmartDeskNative;
}

export function isAndroidBridgeAvailable() {
  return Boolean(window.SmartDeskNative);
}

export function isFaceDetectionAvailable() {
  return Boolean(
    window.SmartDeskNative?.startFaceDetection &&
      window.SmartDeskNative?.stopFaceDetection,
  );
}

export function isIdentityVerificationAvailable() {
  return Boolean(
    window.SmartDeskNative?.startFaceEnrollment &&
      window.SmartDeskNative?.startFaceVerification &&
      window.SmartDeskNative?.getIdentityStatus,
  );
}

export function getDeviceInfo() {
  const payload = requireAndroidBridge().getDeviceInfo();
  return typeof payload === "string" ? JSON.parse(payload) : payload;
}

export function startFaceDetection() {
  const bridge = requireAndroidBridge();
  if (!bridge.startFaceDetection) {
    throw new Error("摄像头功能将在下一阶段实现");
  }
  bridge.startFaceDetection();
}

export function stopFaceDetection() {
  if (!window.SmartDeskNative?.stopFaceDetection) {
    return;
  }
  window.SmartDeskNative.stopFaceDetection();
}

function parseBridgePayload(payload) {
  return typeof payload === "string" ? JSON.parse(payload) : payload;
}

export function getIdentityStatus() {
  return parseBridgePayload(requireAndroidBridge().getIdentityStatus());
}

export function startFaceEnrollment(personId) {
  return parseBridgePayload(
    requireAndroidBridge().startFaceEnrollment(personId),
  );
}

export function startIdentityVerification() {
  return parseBridgePayload(
    requireAndroidBridge().startFaceVerification(),
  );
}

export function stopIdentityVerification() {
  if (!window.SmartDeskNative?.stopFaceVerification) {
    return null;
  }
  return parseBridgePayload(
    window.SmartDeskNative.stopFaceVerification(),
  );
}

export function clearFaceTemplate() {
  return parseBridgePayload(
    requireAndroidBridge().clearFaceTemplate(),
  );
}

export function removeFaceTemplate(personId) {
  return parseBridgePayload(
    requireAndroidBridge().removeFaceTemplate(personId),
  );
}

export function getRegisteredFaces() {
  return parseBridgePayload(
    requireAndroidBridge().getRegisteredFaces(),
  );
}

export function setVerificationThreshold(value) {
  const bridge = requireAndroidBridge();
  const action =
    bridge.applyProvisionalThreshold ??
    bridge.setVerificationThreshold;
  return parseBridgePayload(action.call(bridge, value));
}

export function setFaceDiagnosticsEnabled(enabled) {
  return parseBridgePayload(
    requireAndroidBridge().setFaceDiagnosticsEnabled(enabled),
  );
}

export function clearFaceDiagnostics() {
  return parseBridgePayload(
    requireAndroidBridge().clearFaceDiagnostics(),
  );
}

export function getDeviceConfig() {
  return parseBridgePayload(requireAndroidBridge().getDeviceConfig());
}

export function saveDeviceConfig(config) {
  return parseBridgePayload(
    requireAndroidBridge().saveDeviceConfig(JSON.stringify(config)),
  );
}

export function reloadSeatPage() {
  requireAndroidBridge().reloadSeatPage();
}
