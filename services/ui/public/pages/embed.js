(async () => {
  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }

  const assetPromises = new Map();

  function loadScriptOnce(src) {
    if (assetPromises.has(src)) return assetPromises.get(src);
    const promise = new Promise((resolve, reject) => {
      const existing = document.querySelector(`script[src="${src}"]`);
      if (existing) {
        existing.addEventListener('load', resolve, { once: true });
        existing.addEventListener('error', () => reject(new Error(`Failed to load ${src}`)), { once: true });
        if (existing.dataset.loaded === '1') resolve();
        return;
      }
      const script = document.createElement('script');
      script.src = src;
      script.async = true;
      script.onload = () => { script.dataset.loaded = '1'; resolve(); };
      script.onerror = () => reject(new Error(`Failed to load ${src}`));
      document.head.appendChild(script);
    });
    assetPromises.set(src, promise);
    return promise;
  }

  async function ensureMermaid() {
    if (!window.mermaid) await loadScriptOnce('/vendor/mermaid/mermaid.min.js');
    if (!window.mermaid) throw new Error('Mermaid rendering library is unavailable');
  }

  async function ensureBpmnViewer() {
    if (!window.BpmnJS) await loadScriptOnce('/vendor/bpmn-js/bpmn-viewer.production.min.js');
    if (!window.BpmnJS) throw new Error('BPMN viewer library is unavailable');
  }


  const DEFAULT_DIAGRAM_THEME = {
    bpmn: { fill_color: '#ffffff', stroke_color: '#344054', text_color: '#1f2937', connector_color: '#667085', border_width: 1.5, connector_width: 1.8, font_family: 'Arial, sans-serif', font_size: 14 },
    flowchart: { fill_color: '#ffffff', stroke_color: '#2563eb', text_color: '#111827', connector_color: '#64748b', border_width: 1.5, connector_width: 1.8, font_family: 'Arial, sans-serif', font_size: 14 },
    sequence: { fill_color: '#ffffff', stroke_color: '#2563eb', text_color: '#111827', connector_color: '#475467', border_width: 1.5, connector_width: 1.8, font_family: 'Arial, sans-serif', font_size: 14 },
  };
  let diagramTheme = JSON.parse(JSON.stringify(DEFAULT_DIAGRAM_THEME));

  function normaliseDiagramTheme(value) {
    const incoming = value && typeof value === 'object' ? value : {};
    const out = JSON.parse(JSON.stringify(DEFAULT_DIAGRAM_THEME));
    ['bpmn', 'flowchart', 'sequence'].forEach((type) => {
      const row = incoming[type] && typeof incoming[type] === 'object' ? incoming[type] : {};
      ['fill_color', 'stroke_color', 'text_color', 'connector_color'].forEach((field) => {
        if (/^#[0-9a-fA-F]{6}$/.test(String(row[field] || ''))) out[type][field] = String(row[field]).toLowerCase();
      });
      ['border_width', 'connector_width'].forEach((field) => {
        const n = Number(row[field]);
        if (Number.isFinite(n)) out[type][field] = Math.min(8, Math.max(0.5, n));
      });
      const fs = Number(row.font_size);
      if (Number.isFinite(fs)) out[type].font_size = Math.min(28, Math.max(8, fs));
      const family = String(row.font_family || '').trim();
      if (/^[A-Za-z0-9 ,.'"_-]{1,120}$/.test(family)) out[type].font_family = family;
    });
    return out;
  }

  function themeFor(type) {
    return diagramTheme[type] || diagramTheme.bpmn || DEFAULT_DIAGRAM_THEME.bpmn;
  }

  function applyDiagramThemeCss(type) {
    const t = themeFor(type || 'bpmn');
    const root = document.documentElement;
    root.style.setProperty('--midena-diagram-fill', t.fill_color);
    root.style.setProperty('--midena-diagram-stroke', t.stroke_color);
    root.style.setProperty('--midena-diagram-text', t.text_color);
    root.style.setProperty('--midena-diagram-connector', t.connector_color);
    root.style.setProperty('--midena-diagram-border-width', `${t.border_width}px`);
    root.style.setProperty('--midena-diagram-connector-width', `${t.connector_width}px`);
    root.style.setProperty('--midena-diagram-font-family', t.font_family);
    root.style.setProperty('--midena-diagram-font-size', `${t.font_size}px`);
    document.body.classList.toggle('diagram-theme-bpmn', type === 'bpmn');
  }

  function setSvgAttrs(node, attrs) {
    if (!node) return;
    Object.entries(attrs).forEach(([key, value]) => {
      node.setAttribute(key, String(value));
      try { node.style[key.replace(/-([a-z])/g, (_, ch) => ch.toUpperCase())] = String(value); } catch (_) { /* ignore */ }
    });
  }

  function applyDiagramThemeToRenderedSvg(svg, type) {
    if (!svg) return;
    const t = themeFor(type || 'bpmn');
    svg.setAttribute('font-family', t.font_family);
    svg.querySelectorAll('text, tspan').forEach((node) => setSvgAttrs(node, { fill: t.text_color, 'font-family': t.font_family, 'font-size': t.font_size }));
    const boxSelector = type === 'flowchart'
      ? '.node rect, .node polygon, .node circle, .node ellipse, .node path, rect.label-container, polygon.label-container'
      : (type === 'sequence'
        ? 'rect.actor, rect[class*="actor"], rect[class*="labelBox"], rect[class*="note"], rect[data-midena-label-badge="1"], .actor > rect'
        : '.djs-shape .djs-visual > rect, .djs-shape .djs-visual > circle, .djs-shape .djs-visual > ellipse, .djs-shape .djs-visual > polygon');
    svg.querySelectorAll(boxSelector).forEach((node) => {
      if (node.getAttribute('data-midena-svg-bg') === '1') return;
      setSvgAttrs(node, { fill: t.fill_color, stroke: t.stroke_color, 'stroke-width': t.border_width });
    });
    if (type === 'bpmn') {
      svg.querySelectorAll('.djs-shape .djs-visual > path').forEach((node) => setSvgAttrs(node, {
        stroke: t.stroke_color,
        'stroke-width': t.border_width,
      }));
    }
    const connectorSelector = type === 'flowchart'
      ? '.edgePath path, path.flowchart-link, path[class*="flowchart-link"], .edge-thickness-normal, .edge-thickness-thick, .edge-thickness-invisible'
      : (type === 'sequence'
        ? 'line[class*="messageLine"], path[class*="messageLine"], polyline[class*="messageLine"], line[class*="loopLine"], path[class*="loopLine"], polyline[class*="loopLine"]'
        : '.djs-connection .djs-visual > path, .djs-connection .djs-visual > polyline, .djs-connection .djs-visual > line');
    svg.querySelectorAll(connectorSelector).forEach((node) => setSvgAttrs(node, { stroke: t.connector_color, 'stroke-width': t.connector_width, fill: 'none' }));
    svg.querySelectorAll('marker path, marker polygon').forEach((node) => setSvgAttrs(node, { fill: t.connector_color, stroke: t.connector_color }));
  }

  function escapeMermaidMessage(message) {
    return String(message || '')
      .replace(/\\n\\/g, '<br/>')
      .replace(/\\n/g, '<br/>')
      .replace(/\\\\/g, '\\');
  }

  function convertWebSequenceLine(line) {
    const raw = String(line || '');
    if (!raw.trim()) return raw;
    if (/^\s*(sequenceDiagram|title|participant|actor|autonumber|note\s+(?:left|right|over)|loop|alt|else|opt|par|and|critical|break|rect|end)\b/i.test(raw)) {
      return raw.replace(/\\n\\/g, '<br/>').replace(/\\n/g, '<br/>');
    }
    if (raw.includes('->>') || raw.includes('-->>') || raw.includes('-x') || raw.includes('--x') || raw.includes('-)') || raw.includes('--)')) {
      return raw.replace(/\\n\\/g, '<br/>').replace(/\\n/g, '<br/>');
    }
    const match = raw.match(/^(\s*)(.+?)\s*(--?>|<--?)\s*(.+?)\s*:\s*(.*)$/);
    if (!match) return raw.replace(/\\n\\/g, '<br/>').replace(/\\n/g, '<br/>');
    const [, indent, leftRaw, arrow, rightRaw, messageRaw] = match;
    const left = leftRaw.trim();
    const right = rightRaw.trim();
    const dashed = arrow.includes('--');
    const mermaidArrow = dashed ? '-->>' : '->>';
    const message = escapeMermaidMessage(messageRaw);
    if (arrow.startsWith('<')) return `${indent}${right}${mermaidArrow}${left}: ${message}`;
    return `${indent}${left}${mermaidArrow}${right}: ${message}`;
  }

  const DEFAULT_FLOWCHART_SOURCE = 'flowchart LR\n    A[\"Start\"]\n    B[\"Process\"]\n    C[\"End\"]\n    A-->B\n    B-->C';

  function toMermaid(source) {
    const text = String(source || '').trim();
    if (!text) return 'sequenceDiagram\nparticipant User\nparticipant MIDENA\nUser->>MIDENA: Open diagram';
    const converted = text.split(/\r?\n/).map(convertWebSequenceLine).join('\n');
    return /^sequenceDiagram\b/m.test(text) ? converted : `sequenceDiagram\n${converted}`;
  }

  function toFlowchartMermaid(source) {
    const text = String(source || '').trim();
    if (!text) return DEFAULT_FLOWCHART_SOURCE;
    return /^\s*(?:flowchart|graph)\b/im.test(text) ? text : `flowchart LR\n${text}`;
  }

  function initMermaidSequence() {
    const t = themeFor('sequence');
    window.mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'loose',
      theme: 'base',
      themeVariables: {
        fontFamily: t.font_family,
        fontSize: `${t.font_size}px`,
        actorBkg: t.fill_color,
        actorBorder: t.stroke_color,
        actorTextColor: t.text_color,
        labelBoxBkgColor: t.fill_color,
        labelBoxBorderColor: t.stroke_color,
        labelTextColor: t.text_color,
        signalColor: t.connector_color,
        signalTextColor: t.text_color,
        noteBkgColor: t.fill_color,
        noteBorderColor: t.stroke_color,
        noteTextColor: t.text_color,
      },
    });
  }

  function initMermaidFlowchart() {
    const t = themeFor('flowchart');
    window.mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'loose',
      theme: 'base',
      flowchart: {
        htmlLabels: false,
        nodeSpacing: 70,
        rankSpacing: 90,
        padding: 18,
        wrappingWidth: 240,
      },
      htmlLabels: false,
      themeVariables: {
        primaryColor: t.fill_color,
        primaryTextColor: t.text_color,
        primaryBorderColor: t.stroke_color,
        lineColor: t.connector_color,
        fontFamily: t.font_family,
        fontSize: `${t.font_size}px`,
      },
    });
  }


  function decodePathPart(value) {
    try { return decodeURIComponent(value || ''); } catch (_) { return value || ''; }
  }

  function refFromPath() {
    const parts = String(window.location.pathname || '').split('/').filter(Boolean);
    let id = '';
    let token = '';

    const embedIndex = parts.indexOf('embed');
    if (embedIndex !== -1) {
      id = parts[embedIndex + 1] || '';
      token = parts[embedIndex + 2] || '';
    }

    const publicIndex = parts.indexOf('public');
    if (!id && publicIndex !== -1 && parts[publicIndex + 1] === 'diagrams') {
      id = parts[publicIndex + 2] || '';
      token = parts[publicIndex + 3] || '';
    }

    const params = new URLSearchParams(window.location.search || '');
    id = id || params.get('id') || params.get('diagram') || '';
    token = token || params.get('token') || '';

    return {
      id: decodePathPart(id),
      token: decodePathPart(String(token).replace(/\.html$/i, '')),
    };
  }

  function applyLinks(viewer, entityLinks) {
    if (!viewer) return;
    const overlays = viewer.get('overlays');
    const canvas = viewer.get('canvas');
    const elementRegistry = viewer.get('elementRegistry');
    if (!overlays || !canvas || !elementRegistry) return;

    const byElement = new Map();
    (entityLinks || []).forEach((link) => {
      if (!link?.element_id) return;
      if (!byElement.has(link.element_id)) byElement.set(link.element_id, []);
      byElement.get(link.element_id).push(link);
    });

    byElement.forEach((elementLinks, elementId) => {
      const element = elementRegistry.get(elementId);
      if (!element || element.labelTarget) return;
      const primary = elementLinks.find((link) => link.url) || elementLinks[0];
      const label = primary?.label || primary?.entity_ref || 'Open link';
      canvas.addMarker(element, 'midena-linked-element');
      const html = document.createElement(primary?.url ? 'a' : 'span');
      html.className = 'midena-entity-link-overlay';
      html.textContent = elementLinks.length > 1 ? `${label} +${elementLinks.length - 1}` : label;
      html.title = primary?.url ? `Open ${label}` : label;
      if (primary?.url) {
        html.href = primary.url;
        html.target = '_blank';
        html.rel = 'noopener noreferrer';
        html.addEventListener('click', (event) => event.stopPropagation());
      }
      overlays.add(elementId, { position: { bottom: -26, left: 0 }, html });
    });
  }

  function applyRenderedLinks(svg, diagramType, entityLinks) {
    if (!svg || !window.MIDENA_RENDERED?.applySvgInteractions) return;
    window.MIDENA_RENDERED.applySvgInteractions({
      svg,
      diagramType,
      links: entityLinks || [],
      selectable: false,
    });
  }


  function parseSvgLength(value) {
    const match = String(value ?? '').match(/-?\d+(?:\.\d+)?/);
    return match ? Number(match[0]) : 0;
  }

  function svgDimensions(svg) {
    const viewBox = svg?.viewBox?.baseVal;
    let x = Number.isFinite(viewBox?.x) ? viewBox.x : 0;
    let y = Number.isFinite(viewBox?.y) ? viewBox.y : 0;
    let width = Number.isFinite(viewBox?.width) ? viewBox.width : parseSvgLength(svg?.getAttribute('width'));
    let height = Number.isFinite(viewBox?.height) ? viewBox.height : parseSvgLength(svg?.getAttribute('height'));
    try {
      const box = svg?.getBBox?.();
      if (box) {
        width = Math.max(width, box.width || 0);
        height = Math.max(height, box.height || 0);
        if (!viewBox?.width) {
          x = Math.min(x, box.x || 0);
          y = Math.min(y, box.y || 0);
        }
      }
    } catch (_) { /* ignore */ }
    return { x: Number.isFinite(x) ? x : 0, y: Number.isFinite(y) ? y : 0, width: width > 0 ? width : 1200, height: height > 0 ? height : 800 };
  }

  function ensureWhiteSvgBackground(svg) {
    if (!svg) return;
    const { x, y, width, height } = svgDimensions(svg);
    const ns = 'http://www.w3.org/2000/svg';
    let bg = svg.querySelector(':scope > rect[data-midena-svg-bg="1"]');
    if (!bg) {
      bg = document.createElementNS(ns, 'rect');
      bg.setAttribute('data-midena-svg-bg', '1');
      svg.insertBefore(bg, svg.firstChild);
    }
    bg.setAttribute('x', String(x));
    bg.setAttribute('y', String(y));
    bg.setAttribute('width', String(width));
    bg.setAttribute('height', String(height));
    bg.setAttribute('fill', '#ffffff');
    bg.setAttribute('stroke', 'none');
    bg.setAttribute('pointer-events', 'none');
  }

  function applySequenceLabelBadges(svg) {
    if (!svg) return;
    const ns = 'http://www.w3.org/2000/svg';
    svg.querySelectorAll('rect[data-midena-label-badge="1"]').forEach((node) => node.remove());
    const textNodes = [...svg.querySelectorAll('text')].filter((text) => {
      const classText = `${text.getAttribute('class') || ''} ${text.parentElement?.getAttribute('class') || ''}`;
      return /(messageText|noteText|loopText)/i.test(classText) && String(text.textContent || '').trim();
    });
    const candidates = textNodes.map((text) => {
      let bbox = null;
      const tspans = [...text.querySelectorAll('tspan')];
      if (tspans.length > 1) {
        tspans.forEach((tspan) => {
          try {
            const box = tspan.getBBox();
            if (!box || !Number.isFinite(box.width) || !Number.isFinite(box.height) || box.width <= 0 || box.height <= 0) return;
            if (!bbox) bbox = { x: box.x, y: box.y, width: box.width, height: box.height };
            else {
              const x1 = Math.min(bbox.x, box.x);
              const y1 = Math.min(bbox.y, box.y);
              const x2 = Math.max(bbox.x + bbox.width, box.x + box.width);
              const y2 = Math.max(bbox.y + bbox.height, box.y + box.height);
              bbox = { x: x1, y: y1, width: x2 - x1, height: y2 - y1 };
            }
          } catch (_) { /* ignore */ }
        });
      }
      if (!bbox) {
        try {
          const box = text.getBBox();
          if (box && box.width > 0 && box.height > 0) bbox = { x: box.x, y: box.y, width: box.width, height: box.height };
        } catch (_) { /* ignore */ }
      }
      return bbox ? { text, parent: text.parentElement || svg, bbox } : null;
    }).filter(Boolean);

    const byParent = new Map();
    candidates.forEach((item) => {
      if (!byParent.has(item.parent)) byParent.set(item.parent, []);
      byParent.get(item.parent).push(item);
    });

    function boxesOverlapX(a, b) {
      const left = Math.max(a.x, b.x);
      const right = Math.min(a.x + a.width, b.x + b.width);
      return right >= left - 16;
    }

    function mergeBoxes(items) {
      const x1 = Math.min(...items.map((item) => item.bbox.x));
      const y1 = Math.min(...items.map((item) => item.bbox.y));
      const x2 = Math.max(...items.map((item) => item.bbox.x + item.bbox.width));
      const y2 = Math.max(...items.map((item) => item.bbox.y + item.bbox.height));
      return { x: x1, y: y1, width: x2 - x1, height: y2 - y1 };
    }

    byParent.forEach((items, parent) => {
      const sorted = items.slice().sort((a, b) => (a.bbox.y - b.bbox.y) || (a.bbox.x - b.bbox.x));
      const clusters = [];
      sorted.forEach((item) => {
        const previousCluster = clusters[clusters.length - 1];
        const previousBox = previousCluster ? mergeBoxes(previousCluster) : null;
        const gap = previousBox ? item.bbox.y - (previousBox.y + previousBox.height) : Infinity;
        if (previousCluster && gap <= 14 && boxesOverlapX(previousBox, item.bbox)) previousCluster.push(item);
        else clusters.push([item]);
      });

      clusters.forEach((cluster) => {
        const bbox = mergeBoxes(cluster);
        const padX = 10;
        const padY = 6;
        const rect = document.createElementNS(ns, 'rect');
        rect.setAttribute('data-midena-label-badge', '1');
        rect.setAttribute('x', String(bbox.x - padX));
        rect.setAttribute('y', String(bbox.y - padY));
        rect.setAttribute('width', String(bbox.width + padX * 2));
        rect.setAttribute('height', String(bbox.height + padY * 2));
        rect.setAttribute('rx', '8');
        rect.setAttribute('ry', '8');
        rect.setAttribute('fill', '#ffffff');
        rect.setAttribute('stroke', '#d7c4f6');
        rect.setAttribute('stroke-width', '1');
        rect.setAttribute('pointer-events', 'none');
        parent.insertBefore(rect, cluster[0].text);
      });
    });
  }
  function enhanceSequenceSvg(svg) {
    ensureWhiteSvgBackground(svg);
    applySequenceLabelBadges(svg);
  }
  function showSavedRenderedSvg(diagram, diagramType, enhance) {
    const canvas = document.getElementById('canvas');
    const svgXml = String(diagram?.svg_xml || '');
    if (!canvas || (diagram?.diagram_type || 'bpmn') !== diagramType || !svgXml.includes('<svg')) return false;
    canvas.classList.add('sequence-embed-canvas');
    canvas.innerHTML = svgXml;
    const svg = canvas.querySelector('svg');
    if (!svg) return false;
    enhance?.(svg);
    applyDiagramThemeToRenderedSvg(svg, diagramType);
    applyRenderedLinks(svg, diagramType, diagram.entity_links || []);
    return true;
  }

  async function renderSequence(diagram) {
    const canvas = document.getElementById('canvas');
    canvas.classList.add('sequence-embed-canvas');
    const source = toMermaid(diagram.sequence_text || diagram.source_text || diagram.bpmn_xml || 'participant User\nparticipant MIDENA\nUser->>MIDENA: Open diagram');
    if (showSavedRenderedSvg(diagram, 'sequence', enhanceSequenceSvg)) return;
    try {
      await ensureMermaid();
      initMermaidSequence();
      const result = await window.mermaid.render(`midena-embed-${Date.now()}`, source);
      canvas.innerHTML = result.svg;
      const svg = canvas.querySelector('svg');
      enhanceSequenceSvg(svg);
      applyDiagramThemeToRenderedSvg(svg, 'sequence');
      applyRenderedLinks(svg, 'sequence', diagram.entity_links || []);
    } catch (err) {
      canvas.innerHTML = `<div class="p-3 text-danger">Could not render sequence diagram.</div><pre>${escapeHtml(source)}</pre>`;
    }
  }

  async function renderFlowchart(diagram) {
    const canvas = document.getElementById('canvas');
    canvas.classList.add('sequence-embed-canvas');
    const source = toFlowchartMermaid(diagram.flowchart_text || diagram.source_text || diagram.bpmn_xml || '');
    if (showSavedRenderedSvg(diagram, 'flowchart', ensureWhiteSvgBackground)) return;
    try {
      await ensureMermaid();
      initMermaidFlowchart();
      const result = await window.mermaid.render(`midena-embed-${Date.now()}`, source);
      canvas.innerHTML = result.svg;
      const svg = canvas.querySelector('svg');
      ensureWhiteSvgBackground(svg);
      applyDiagramThemeToRenderedSvg(svg, 'flowchart');
      applyRenderedLinks(svg, 'flowchart', diagram.entity_links || []);
    } catch (err) {
      canvas.innerHTML = `<div class="p-3 text-danger">Could not render flowchart.</div><pre>${escapeHtml(source)}</pre>`;
    }
  }

  const ref = refFromPath();
  if (!ref.id || !ref.token) { document.body.textContent = 'No public diagram token supplied.'; return; }
  const response = await fetch(`/v1/public/diagrams/${encodeURIComponent(ref.id)}/${encodeURIComponent(ref.token)}`, { credentials: 'omit' });
  if (!response.ok) { document.body.textContent = response.status === 404 ? 'Diagram not found or not public.' : 'Failed to load diagram.'; return; }
  const diagram = await response.json();
  diagramTheme = normaliseDiagramTheme(diagram.diagram_theme);
  applyDiagramThemeCss(diagram.diagram_type || 'bpmn');
  document.title = `${diagram.name} · MIDENA`;
  document.getElementById('diagramHeader').textContent = diagram.header_text || '';
  document.getElementById('diagramFooter').textContent = diagram.footer_text || '';
  if ((diagram.diagram_type || 'bpmn') === 'sequence') {
    await renderSequence(diagram);
    return;
  }
  if ((diagram.diagram_type || 'bpmn') === 'flowchart') {
    await renderFlowchart(diagram);
    return;
  }
  await ensureBpmnViewer();
  const viewer = new BpmnJS({ container: '#canvas' });
  await viewer.importXML(diagram.bpmn_xml);
  viewer.get('canvas').resized?.();
  viewer.get('canvas').zoom('fit-viewport');
  applyLinks(viewer, diagram.entity_links || []);
})();
