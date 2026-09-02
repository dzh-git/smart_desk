import test from "node:test";
import assert from "node:assert/strict";
import {
  buildProvisioningPayload,
  isConfigurationVisible,
  readDeploymentPrefill,
  seatAlias,
  usesAdvancedEndpoints,
} from "./configWorkflow.js";

test("derives human-readable seat aliases", () => {
  assert.equal(seatAlias(1), "tablet-seat-01");
  assert.equal(seatAlias(9), "tablet-seat-09");
});

test("only exposes configuration in setup or unlocked maintenance", () => {
  assert.equal(isConfigurationVisible("setup"), true);
  assert.equal(isConfigurationVisible("maintenance"), true);
  assert.equal(isConfigurationVisible("offline"), false);
  assert.equal(isConfigurationVisible("binding-error"), false);
});

test("detects non-default endpoint overrides", () => {
  assert.equal(
    usesAdvancedEndpoints({
      centralHost: "http://192.168.1.10",
      serverBaseUrl: "http://192.168.1.10:8000",
      frontendBaseUrl: "http://192.168.1.10:5173",
    }),
    false,
  );
  assert.equal(
    usesAdvancedEndpoints({
      centralHost: "https://meeting.example.test",
      serverBaseUrl: "https://api.example.test",
      frontendBaseUrl: "https://meeting.example.test",
    }),
    true,
  );
});

test("never sends a local device token and omits PIN after setup", () => {
  const payload = buildProvisioningPayload(
    {
      seatId: "3",
      centralHost: "192.168.1.10",
      serverBaseUrl: "",
      frontendBaseUrl: "",
      provisioningToken: "admin-provisioning-token-000003",
      maintenancePin: "123456",
      replaceExisting: false,
      deviceToken: "must-not-leak",
    },
    { maintenancePinConfigured: true },
    false,
  );

  assert.equal(payload.seatId, 3);
  assert.equal(payload.maintenancePin, null);
  assert.equal("deviceToken" in payload, false);
});

test("reads only validated non-secret deployment prefill values", () => {
  assert.deepEqual(
    readDeploymentPrefill(
      "?mode=setup&seatId=2&centralHost=http%3A%2F%2F192.168.137.1",
    ),
    { seatId: 2, centralHost: "http://192.168.137.1" },
  );
  assert.deepEqual(
    readDeploymentPrefill(
      "?mode=setup&seatId=10&centralHost=http%3A%2F%2Fhost&maintenancePin=should-not-be-read",
    ),
    {},
  );
});
