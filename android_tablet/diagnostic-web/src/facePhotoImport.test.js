import assert from "node:assert/strict";
import test from "node:test";
import {
  buildFacePhotoPayload,
  validateFacePhotoFiles,
} from "./facePhotoImport.js";

function photo(name, type = "image/jpeg", size = 1024) {
  return { name, type, size };
}

test("accepts 5 to 20 JPEG or PNG photos", () => {
  const files = [
    photo("1.jpg"),
    photo("2.jpg"),
    photo("3.png", "image/png"),
    photo("4.jpg"),
    photo("5.jpg"),
  ];
  assert.equal(validateFacePhotoFiles(files).length, 5);
});

test("rejects invalid count, format, and oversized photos", () => {
  assert.throws(
    () => validateFacePhotoFiles([photo("1.jpg")]),
    /5–20/,
  );
  assert.throws(
    () => validateFacePhotoFiles(Array(5).fill(photo("face.gif", "image/gif"))),
    /JPG 或 PNG/,
  );
  assert.throws(
    () => validateFacePhotoFiles(Array(5).fill(photo("face.jpg", "image/jpeg", 6 * 1024 * 1024))),
    /5 MB/,
  );
});

test("builds a secret-free bridge payload", async () => {
  const files = Array.from({ length: 5 }, (_, index) =>
    photo(`${index + 1}.jpg`),
  );
  const payload = await buildFacePhotoPayload(
    files,
    async () => "data:image/jpeg;base64,YWJj",
  );
  assert.deepEqual(payload[0], {
    name: "1.jpg",
    mimeType: "image/jpeg",
    base64: "YWJj",
  });
  assert.equal(JSON.stringify(payload).includes("provisioningToken"), false);
});
