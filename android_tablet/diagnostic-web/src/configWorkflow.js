export function seatAlias(seatId) {
  return `tablet-seat-${String(Number(seatId)).padStart(2, "0")}`;
}

export function isConfigurationVisible(mode) {
  return mode === "setup" || mode === "maintenance";
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
