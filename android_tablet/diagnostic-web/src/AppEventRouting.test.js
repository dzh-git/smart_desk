import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("./App.jsx", import.meta.url), "utf8");

test("keeps face registration and threshold management out of diagnostics", () => {
  assert.doesNotMatch(source, /上传参会者照片/);
  assert.doesNotMatch(source, /注册双光照 5\+5 帧/);
  assert.doesNotMatch(source, /应用 PROVISIONAL 阈值/);
  assert.match(source, /人脸注册、阈值确认和席位分配统一在主持人人脸模板管理页完成/);
});
