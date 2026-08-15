export const MIN_FACE_PHOTOS = 5;
export const MAX_FACE_PHOTOS = 20;
export const MAX_FACE_PHOTO_BYTES = 5 * 1024 * 1024;
export const MAX_FACE_PHOTO_TOTAL_BYTES = 50 * 1024 * 1024;

export function validateFacePhotoFiles(files) {
  const selected = Array.from(files ?? []);
  if (
    selected.length < MIN_FACE_PHOTOS ||
    selected.length > MAX_FACE_PHOTOS
  ) {
    throw new Error(`请选择 ${MIN_FACE_PHOTOS}–${MAX_FACE_PHOTOS} 张照片`);
  }
  let totalBytes = 0;
  selected.forEach((file) => {
    const mimeType = normalizeMimeType(file.type);
    if (mimeType !== "image/jpeg" && mimeType !== "image/png") {
      throw new Error(`${file.name}：只支持 JPG 或 PNG`);
    }
    if (!Number.isFinite(file.size) || file.size <= 0) {
      throw new Error(`${file.name}：文件为空`);
    }
    if (file.size > MAX_FACE_PHOTO_BYTES) {
      throw new Error(`${file.name}：单张照片不得超过 5 MB`);
    }
    totalBytes += file.size;
  });
  if (totalBytes > MAX_FACE_PHOTO_TOTAL_BYTES) {
    throw new Error("照片总大小不得超过 50 MB");
  }
  return selected;
}

export async function buildFacePhotoPayload(
  files,
  readDataUrl = readFileAsDataUrl,
) {
  const selected = validateFacePhotoFiles(files);
  const payload = [];
  for (const file of selected) {
    const dataUrl = await readDataUrl(file);
    const comma = dataUrl.indexOf(",");
    if (comma < 0) {
      throw new Error(`${file.name}：无法读取照片数据`);
    }
    payload.push({
      name: file.name,
      mimeType: normalizeMimeType(file.type),
      base64: dataUrl.slice(comma + 1),
    });
  }
  return payload;
}

function normalizeMimeType(value) {
  return value === "image/jpg" ? "image/jpeg" : value;
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error(`${file.name}：读取失败`));
    reader.readAsDataURL(file);
  });
}
