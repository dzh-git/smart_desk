import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("./App.jsx", import.meta.url), "utf8");

function functionBody(startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  assert.notEqual(start, -1, `${startMarker} must exist`);
  assert.notEqual(end, -1, `${endMarker} must exist after ${startMarker}`);
  return source.slice(start, end);
}

test("routes face photo import results through the native event handler", () => {
  const eventHandler = functionBody(
    "function handleAndroidEvent(event)",
    "function testBridge()",
  );
  const provisioningHandler = functionBody(
    "function persistDeviceConfig(event)",
    "function openSeatPage()",
  );

  assert.match(eventHandler, /face_photo_import_result/);
  assert.doesNotMatch(provisioningHandler, /face_photo_import_result/);
});
