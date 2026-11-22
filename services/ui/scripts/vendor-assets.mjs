import fs from "node:fs";
import path from "node:path";

import { checkGitPackages } from "./vendor-guard.mjs";

const root = process.cwd();
const nm = (...parts) => path.join(root, "node_modules", ...parts);
const out = (...parts) => path.join(root, "public", "vendor", ...parts);

// Nothing is copied from a dependency fetched from a git host unless its tree
// is the one reviewed (scripts/vendor-guard.mjs). Without the lockfile
// nothing can be told apart, so the build stops.
checkGitPackages(root);

// Every vendored file is required: a page that loads a missing script would
// fail in the browser instead of at build time.
function copy(src, dest) {
  if (!fs.existsSync(src)) {
    throw new Error(
      `Required vendored asset is missing: ${src}. Run npm ci first.`,
    );
  }
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(src, dest);
}

function copyDir(src, dest) {
  if (!fs.existsSync(src)) {
    throw new Error(`Required vendored directory is missing: ${src}.`);
  }
  fs.mkdirSync(dest, { recursive: true });
  fs.cpSync(src, dest, { recursive: true });
}

copy(
  nm("bootstrap", "dist", "css", "bootstrap.min.css"),
  out("bootstrap", "bootstrap.min.css"),
);
copy(
  nm("bootstrap", "dist", "js", "bootstrap.bundle.min.js"),
  out("bootstrap", "bootstrap.bundle.min.js"),
);
copy(
  nm("bootstrap-icons", "font", "bootstrap-icons.min.css"),
  out("bootstrap-icons", "bootstrap-icons.min.css"),
);
copy(
  nm("bootstrap-icons", "font", "fonts", "bootstrap-icons.woff"),
  out("bootstrap-icons", "fonts", "bootstrap-icons.woff"),
);
copy(
  nm("bootstrap-icons", "font", "fonts", "bootstrap-icons.woff2"),
  out("bootstrap-icons", "fonts", "bootstrap-icons.woff2"),
);

copy(nm("jspdf", "dist", "jspdf.umd.min.js"), out("jspdf", "jspdf.umd.min.js"));
copy(
  nm("html2canvas", "dist", "html2canvas.min.js"),
  out("html2canvas", "html2canvas.min.js"),
);
copy(nm("mermaid", "dist", "mermaid.min.js"), out("mermaid", "mermaid.min.js"));

copy(
  nm("bpmn-js", "dist", "bpmn-modeler.production.min.js"),
  out("bpmn-js", "bpmn-modeler.production.min.js"),
);
copy(
  nm("bpmn-js", "dist", "bpmn-viewer.production.min.js"),
  out("bpmn-js", "bpmn-viewer.production.min.js"),
);
copyDir(nm("bpmn-js", "dist", "assets"), out("bpmn-js", "assets"));

// MOSP design system (first-party, pinned by commit, tree reviewed above).
for (const file of [
  "styles.css",
  "app.js",
  "theme-boot.js",
  "BUILD_INFO.txt",
]) {
  copy(
    nm("@fercbusters", "mosp-design-system", "dist", file),
    out("mosp-design-system", file),
  );
}
copy(
  nm("@fercbusters", "mosp-design-system", "LICENSE"),
  out("mosp-design-system", "LICENSE"),
);

console.log("Vendored assets into public/vendor");
