import fs from 'node:fs';
import path from 'node:path';

function copyIfExists(src, dest) {
  if (!fs.existsSync(src)) {
    console.warn(`Skip (missing): ${src}`);
    return;
  }
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(src, dest);
  console.log(`Vendored ${src} -> ${dest}`);
}

function copyDirIfExists(src, dest) {
  if (!fs.existsSync(src)) {
    console.warn(`Skip dir (missing): ${src}`);
    return;
  }
  fs.mkdirSync(dest, { recursive: true });
  fs.cpSync(src, dest, { recursive: true });
  console.log(`Vendored ${src} -> ${dest}`);
}

const root = process.cwd();
const nm = (...parts) => path.join(root, 'node_modules', ...parts);
const out = (...parts) => path.join(root, 'public', 'vendor', ...parts);

copyIfExists(nm('bootstrap', 'dist', 'css', 'bootstrap.min.css'), out('bootstrap', 'bootstrap.min.css'));
copyIfExists(nm('bootstrap', 'dist', 'js', 'bootstrap.bundle.min.js'), out('bootstrap', 'bootstrap.bundle.min.js'));
copyIfExists(nm('bootstrap-icons', 'font', 'bootstrap-icons.min.css'), out('bootstrap-icons', 'bootstrap-icons.min.css'));
copyIfExists(nm('bootstrap-icons', 'font', 'fonts', 'bootstrap-icons.woff'), out('bootstrap-icons', 'fonts', 'bootstrap-icons.woff'));
copyIfExists(nm('bootstrap-icons', 'font', 'fonts', 'bootstrap-icons.woff2'), out('bootstrap-icons', 'fonts', 'bootstrap-icons.woff2'));

copyIfExists(nm('d3', 'dist', 'd3.min.js'), out('d3', 'd3.min.js'));
copyIfExists(nm('jspdf', 'dist', 'jspdf.umd.min.js'), out('jspdf', 'jspdf.umd.min.js'));
copyIfExists(nm('html2canvas', 'dist', 'html2canvas.min.js'), out('html2canvas', 'html2canvas.min.js'));
copyIfExists(nm('mermaid', 'dist', 'mermaid.min.js'), out('mermaid', 'mermaid.min.js'));

copyIfExists(nm('bpmn-js', 'dist', 'bpmn-modeler.production.min.js'), out('bpmn-js', 'bpmn-modeler.production.min.js'));
copyIfExists(nm('bpmn-js', 'dist', 'bpmn-viewer.production.min.js'), out('bpmn-js', 'bpmn-viewer.production.min.js'));
copyDirIfExists(nm('bpmn-js', 'dist', 'assets'), out('bpmn-js', 'assets'));

copyIfExists(nm('@FERCBusters', 'mosp-design-system', 'dist', 'styles.css'), out('mosp-design-system', 'styles.css'));
copyIfExists(nm('@FERCBusters', 'mosp-design-system', 'dist', 'app.js'), out('mosp-design-system', 'app.js'));
copyIfExists(nm('@FERCBusters', 'mosp-design-system', 'dist', 'BUILD_INFO.txt'), out('mosp-design-system', 'BUILD_INFO.txt'));

console.log('Vendored assets into public/vendor');
