export function seatAlias(seatId) {
  return `tablet-seat-${String(Number(seatId)).padStart(2, "0")}`;
}

export function isConfigurationVisible(mode) {
  return mode === "setup" || mode === "maintenance";
}

export function readDeploymentPrefill(search) {
  const params = new URLSearchParams(search);
  if (params.get("mode") !== "setup") return {};
  const seatId = Number(params.get("seatId"));
  if (!Number.isInteger(seatId) || seatId < 1 || seatId > 9) return {};
  try {
    const url = new URL(params.get("centralHost") ?? "");
    if (
      !["http:", "https:"].includes(url.protocol) ||
      url.username ||
      url.password ||
      url.port ||
      (url.pathname && url.pathname !== "/") ||
      url.search ||
      url.hash
    ) {
      return {};
    }
    return { seatId, centralHost: url.origin };
  } catch {
    return {};
  }
}

export function usesAdvancedEndpoints(config) {
  const host = config?.centralHost?.replace(/\/$/, "");
  if (!host) return false;
  const server = config.serverBaseUrl ?? config.serverUrl;
  const frontend = config.frontendBaseUrl ?? config.frontendUrl;
  return server !== `${host}:8000` || frontend !== `${host}:5173`;
}

export function buildProvisioningPayload(
  config,
  device,
  showAdvancedUrls,
) {
  return {
    seatId: Number(config.seatId),
    centralHost: config.centralHost,
    serverBaseUrl: showAdvancedUrls ? config.serverBaseUrl : null,
    frontendBaseUrl: showAdvancedUrls ? config.frontendBaseUrl : null,
    provisioningToken: config.provisioningToken,
    maintenancePin: device.maintenancePinConfigured
      ? null
      : config.maintenancePin,
    replaceExisting: Boolean(config.replaceExisting),
  };
}
