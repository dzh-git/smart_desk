import { cp, mkdir, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const reactRoot = path.resolve(scriptDirectory, "..");
const source = path.join(reactRoot, "dist");
const destination = path.resolve(
  reactRoot,
  "../android-app/app/src/main/assets/web",
);

await rm(destination, { recursive: true, force: true });
await mkdir(destination, { recursive: true });
await cp(source, destination, { recursive: true });

console.log(`Copied React build to ${destination}`);
