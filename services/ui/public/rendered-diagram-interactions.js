(() => {
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const XLINK_NS = 'http://www.w3.org/1999/xlink';

  function cleanText(value) {
    return String(value ?? '').replace(/\s+/g, ' ').trim();
  }

  function hashString(value) {
    let hash = 0;
    const text = String(value ?? '');
    for (let idx = 0; idx < text.length; idx += 1) {
      hash = ((hash << 5) - hash) + text.charCodeAt(idx);
      hash |= 0;
    }
    return Math.abs(hash).toString(36);
  }

  function makeElementId(prefix, value) {
    const clean = cleanText(value) || 'item';
    const id = `${prefix}:${clean}`;
    if (id.length <= 240) return id;
    return `${prefix}:${clean.slice(0, 190)}:${hashString(clean)}`;
  }

  function truncate(value, maxLength = 28) {
    const text = cleanText(value);
    return text.length > maxLength ? `${text.slice(0, Math.max(1, maxLength - 1))}…` : text;
  }

  function rootSvgFor(element) {
    if (!element) return null;
    if (String(element.nodeName || '').toLowerCase() === 'svg') return element;
    return element.ownerSVGElement || null;
  }

  function matrixRelativeToSvg(element, svg) {
    if (!element || !svg || element === svg) return null;
    try {
      const elementCtm = element.getScreenCTM?.();
      const svgCtm = svg.getScreenCTM?.();
      if (!elementCtm || !svgCtm) return null;
      return svgCtm.inverse().multiply(elementCtm);
    } catch (_) {
      return null;
    }
  }

  function transformPoint(svg, matrix, x, y) {
    const point = svg.createSVGPoint();
    point.x = x;
    point.y = y;
    return point.matrixTransform(matrix);
  }

  function transformBoxToSvgCoords(box, element, svg) {
    const matrix = matrixRelativeToSvg(element, svg);
    if (!matrix) return box;
    try {
      const corners = [
        transformPoint(svg, matrix, box.x, box.y),
        transformPoint(svg, matrix, box.x + box.width, box.y),
        transformPoint(svg, matrix, box.x, box.y + box.height),
        transformPoint(svg, matrix, box.x + box.width, box.y + box.height),
      ];
      const xs = corners.map((point) => point.x);
      const ys = corners.map((point) => point.y);
      const x1 = Math.min(...xs);
      const y1 = Math.min(...ys);
      const x2 = Math.max(...xs);
      const y2 = Math.max(...ys);
      return { x: x1, y: y1, width: x2 - x1, height: y2 - y1 };
    } catch (_) {
      return box;
    }
  }

  function svgBox(element) {
    if (!element?.getBBox) return null;
    try {
      const box = element.getBBox();
      if (!box || !Number.isFinite(box.x) || !Number.isFinite(box.y) || !Number.isFinite(box.width) || !Number.isFinite(box.height) || box.width <= 0 || box.height <= 0) return null;
      const rawBox = { x: box.x, y: box.y, width: box.width, height: box.height };
      const svg = rootSvgFor(element);
      return svg ? transformBoxToSvgCoords(rawBox, element, svg) : rawBox;
    } catch (_) {
      return null;
    }
  }

  function paddedBox(box, padX = 0, padY = padX) {
    if (!box) return null;
    return { x: box.x - padX, y: box.y - padY, width: box.width + padX * 2, height: box.height + padY * 2 };
  }

  function mergeBoxes(a, b) {
    if (!a) return b;
    if (!b) return a;
    const x1 = Math.min(a.x, b.x);
    const y1 = Math.min(a.y, b.y);
    const x2 = Math.max(a.x + a.width, b.x + b.width);
    const y2 = Math.max(a.y + a.height, b.y + b.height);
    return { x: x1, y: y1, width: x2 - x1, height: y2 - y1 };
  }

  function addTarget(targets, id, label, box, kind = 'item') {
    if (!id || !box || box.width <= 0 || box.height <= 0) return;
    const existing = targets.get(id) || { id, label: cleanText(label) || id, kind, boxes: [] };
    existing.label = existing.label || cleanText(label) || id;
    existing.kind = existing.kind || kind;
    existing.boxes.push(box);
    targets.set(id, existing);
  }

  function nodeText(node) {
    return cleanText(node?.textContent || '');
  }

  function elementClassText(element) {
    return `${element?.getAttribute?.('class') || ''} ${element?.parentElement?.getAttribute?.('class') || ''}`;
  }

  function closestUsefulGroup(node, svg, maxWidth = 520, maxHeight = 180) {
    const ownBox = svgBox(node);
    let current = node?.parentElement;
    while (current && current !== svg) {
      if (String(current.nodeName || '').toLowerCase() === 'g') {
        const groupBox = svgBox(current);
        if (groupBox && (!ownBox || (
          groupBox.width >= ownBox.width &&
          groupBox.height >= ownBox.height &&
          groupBox.width <= Math.max(maxWidth, ownBox.width + 220) &&
          groupBox.height <= Math.max(maxHeight, ownBox.height + 100)
        ))) return current;
      }
      current = current.parentElement;
    }
    return node;
  }



  function actorBoxForText(text, svg) {
    const textBox = svgBox(text);
    if (!textBox) return null;
    const cx = textBox.x + textBox.width / 2;
    const cy = textBox.y + textBox.height / 2;
    let best = null;
    let bestDistance = Infinity;
    [...svg.querySelectorAll('rect')].filter((rect) => /\bactor\b/i.test(elementClassText(rect))).forEach((rect) => {
      const rectBox = svgBox(rect);
      if (!rectBox) return;
      const insideX = cx >= rectBox.x - 24 && cx <= rectBox.x + rectBox.width + 24;
      const nearY = cy >= rectBox.y - 24 && cy <= rectBox.y + rectBox.height + 24;
      if (!insideX || !nearY) return;
      const rcx = rectBox.x + rectBox.width / 2;
      const rcy = rectBox.y + rectBox.height / 2;
      const distance = Math.abs(cx - rcx) + Math.abs(cy - rcy);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = mergeBoxes(rectBox, textBox);
      }
    });
    return best || textBox;
  }

  function flowchartNodeRef(group, index, label) {
    let raw = cleanText(group.getAttribute('data-id') || group.id || '');
    if (raw.startsWith('flowchart-')) raw = raw.slice('flowchart-'.length);
    raw = raw.replace(/-\d+$/u, '');
    if (!raw || /^subGraph\d+$/iu.test(raw)) raw = label || `node ${index + 1}`;
    return raw;
  }

  function discoverFlowchartTargets(svg) {
    const targets = new Map();
    const nodes = [...svg.querySelectorAll('g.node')].filter((node) => !node.closest('[data-midena-rendered-overlay-layer="1"]'));
    nodes.forEach((node, index) => {
      const label = nodeText(node) || `Node ${index + 1}`;
      const ref = flowchartNodeRef(node, index, label);
      addTarget(targets, makeElementId('flowchart', ref), label, paddedBox(svgBox(node), 4, 4), 'flowchart node');
    });
    return targets;
  }

  function discoverSequenceTargets(svg) {
    const targets = new Map();
    const actorTexts = [...svg.querySelectorAll('text')].filter((text) => /\bactor\b/i.test(elementClassText(text)) && nodeText(text));
    actorTexts.forEach((text) => {
      const label = nodeText(text);
      const group = closestUsefulGroup(text, svg, 420, 120);
      const box = paddedBox(actorBoxForText(text, svg) || svgBox(group) || svgBox(text), 8, 6);
      addTarget(targets, makeElementId('sequence:participant', label), label, box, 'participant');
    });

    const labelledTexts = [...svg.querySelectorAll('text')].filter((text) => {
      const classes = elementClassText(text);
      return /(messageText|noteText|loopText)/i.test(classes) && nodeText(text);
    });
    labelledTexts.forEach((text, index) => {
      const label = nodeText(text);
      const group = closestUsefulGroup(text, svg, 640, 180);
      const textBox = svgBox(text);
      const groupBox = svgBox(group);
      const box = paddedBox(groupBox && textBox && groupBox.width <= Math.max(640, textBox.width + 260) ? groupBox : textBox, 10, 7);
      addTarget(targets, makeElementId('sequence:message', `${index + 1}:${label}`), label, box, 'message');
    });
    return targets;
  }

  function discoverTargets(svg, diagramType) {
    if (!svg) return new Map();
    return diagramType === 'flowchart' ? discoverFlowchartTargets(svg) : discoverSequenceTargets(svg);
  }

  function groupByElement(items) {
    const grouped = new Map();
    (items || []).forEach((item) => {
      if (!item?.element_id) return;
      if (!grouped.has(item.element_id)) grouped.set(item.element_id, []);
      grouped.get(item.element_id).push(item);
    });
    return grouped;
  }

  function svgEl(name, attrs = {}) {
    const node = document.createElementNS(SVG_NS, name);
    Object.entries(attrs).forEach(([key, value]) => {
      if (value === undefined || value === null) return;
      node.setAttribute(key, String(value));
    });
    return node;
  }

  function appendTitle(node, value) {
    const text = cleanText(value);
    if (!node || !text) return;
    const title = svgEl('title');
    title.textContent = text;
    node.appendChild(title);
  }

  function primaryLinkFor(elementLinks) {
    return (elementLinks || []).find((link) => link?.url) || null;
  }

  function labelForLink(link) {
    return link?.label || link?.entity_ref || 'Open link';
  }

  function setAnchorTarget(anchor, url) {
    if (!anchor || !url) return;
    anchor.setAttribute('href', url);
    anchor.setAttributeNS(XLINK_NS, 'xlink:href', url);
    anchor.setAttribute('target', '_blank');
    anchor.setAttribute('rel', 'noopener noreferrer');
    anchor.addEventListener?.('click', (event) => event.stopPropagation());
  }

  function drawLinkPill(layer, target, box, elementLinks) {
    if (!elementLinks?.length) return;
    const primary = primaryLinkFor(elementLinks) || elementLinks[0];
    const rawLabel = labelForLink(primary);
    const label = elementLinks.length > 1 ? `${truncate(rawLabel, 22)} +${elementLinks.length - 1}` : truncate(rawLabel, 26);
    const pillWidth = Math.max(54, Math.min(220, label.length * 7.3 + 24));
    const pillHeight = 20;
    const x = box.x;
    const y = box.y + box.height + 7;
    const anchor = svgEl(primary?.url ? 'a' : 'g');
    if (primary?.url) setAnchorTarget(anchor, primary.url);
    anchor.setAttribute('class', 'midena-rendered-link-pill');
    appendTitle(anchor, primary?.url ? `Open ${rawLabel}` : rawLabel);
    anchor.appendChild(svgEl('rect', { x, y, width: pillWidth, height: pillHeight, rx: 10, ry: 10 }));
    const text = svgEl('text', { x: x + 10, y: y + 14 });
    text.textContent = `${label} ↗`;
    anchor.appendChild(text);
    layer.appendChild(anchor);
  }

  function drawCommentPill(layer, target, box, elementComments, onCommentClick) {
    if (!elementComments?.length) return;
    const count = elementComments.length;
    const label = count > 1 ? `💬 ${count}` : '💬';
    const width = count > 1 ? 34 : 24;
    const height = 20;
    const x = box.x + box.width - width + 2;
    const y = box.y - height - 4;
    const group = svgEl('g', { class: 'midena-rendered-comment-pill', tabindex: '0', role: 'button' });
    appendTitle(group, elementComments.slice(0, 4).map((comment) => `${comment.username || 'user'}: ${comment.body || ''}`).join('\n'));
    group.appendChild(svgEl('rect', { x, y, width, height, rx: 8, ry: 8 }));
    const text = svgEl('text', { x: x + width / 2, y: y + 14, 'text-anchor': 'middle' });
    text.textContent = label;
    group.appendChild(text);
    group.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      onCommentClick?.(elementComments[0], target);
    });
    group.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      onCommentClick?.(elementComments[0], target);
    });
    layer.appendChild(group);
  }

  function drawTargetHitbox(layer, target, box, flags, onSelect) {
    const hit = svgEl('rect', {
      class: [
        'midena-rendered-target-hit',
        flags.selected ? 'selected' : '',
        flags.linked ? 'linked' : '',
        flags.commented ? 'commented' : '',
        flags.linkUrl ? 'link-anchor' : '',
      ].filter(Boolean).join(' '),
      x: box.x,
      y: box.y,
      width: box.width,
      height: box.height,
      rx: 8,
      ry: 8,
      tabindex: '0',
      role: flags.linkUrl ? 'link' : 'button',
      'data-midena-rendered-target': target.id,
      'pointer-events': 'all',
    });

    if (flags.inlineStyle) {
      const fill = flags.linkUrl ? 'rgba(111, 66, 193, 0.01)' : 'rgba(111, 66, 193, 0.025)';
      const stroke = flags.selected || flags.linked ? '#6f42c1' : (flags.commented ? '#b58100' : 'transparent');
      hit.setAttribute('fill', fill);
      hit.setAttribute('stroke', stroke);
      hit.setAttribute('stroke-width', '2');
      hit.setAttribute('stroke-dasharray', '6 4');
      hit.setAttribute('style', `cursor:pointer;pointer-events:all;fill:${fill};stroke:${stroke};stroke-width:2;stroke-dasharray:6 4;`);
    }

    if (flags.linkUrl) {
      const anchor = svgEl('a', {
        class: 'midena-rendered-target-link',
        'data-midena-rendered-target-link': target.id,
      });
      setAnchorTarget(anchor, flags.linkUrl);
      appendTitle(anchor, `Open ${flags.linkLabel || target.label}`);
      anchor.appendChild(hit);
      layer.appendChild(anchor);
      return;
    }

    appendTitle(hit, `Select ${target.label}`);
    hit.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      onSelect?.(target.id, target);
    });
    hit.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      onSelect?.(target.id, target);
    });
    layer.appendChild(hit);
  }


  function removeOverlayLayers(svg) {
    svg?.querySelectorAll?.('[data-midena-rendered-overlay-layer="1"]')?.forEach((node) => node.remove());
  }

  function applySvgInteractions(options = {}) {
    const svg = options.svg;
    if (!svg) return new Map();
    removeOverlayLayers(svg);
    const targets = discoverTargets(svg, options.diagramType || 'sequence');
    const linkMap = groupByElement(options.links || []);
    const commentMap = groupByElement((options.comments || []).filter((comment) => !comment.is_resolved));
    if (!targets.size) return targets;
    const selectable = options.selectable !== false;
    const openTargetLinks = options.openTargetLinks === true || !selectable;
    const inlineStyles = options.inlineStyles === true;
    const showLinkPills = options.showLinkPills !== false;
    const layer = svgEl('g', { 'data-midena-rendered-overlay-layer': '1', class: 'midena-rendered-overlay-layer' });
    svg.appendChild(layer);
    targets.forEach((target) => {
      const elementLinks = linkMap.get(target.id) || [];
      const elementComments = commentMap.get(target.id) || [];
      const primaryLink = primaryLinkFor(elementLinks);
      target.boxes.forEach((rawBox, index) => {
        const box = paddedBox(rawBox, 2, 2);
        const linkUrl = openTargetLinks && primaryLink?.url ? primaryLink.url : '';
        const linkLabel = primaryLink ? labelForLink(primaryLink) : '';
        if (selectable || linkUrl) {
          drawTargetHitbox(layer, target, box, {
            selected: options.selectedElementId === target.id,
            linked: Boolean(elementLinks.length),
            commented: Boolean(elementComments.length),
            linkUrl,
            linkLabel,
            inlineStyle: inlineStyles,
          }, options.onSelect);
        } else if (elementLinks.length || elementComments.length) {
          const marker = svgEl('rect', {
            class: [
              'midena-rendered-target-hit',
              elementLinks.length ? 'linked' : '',
              elementComments.length ? 'commented' : '',
            ].filter(Boolean).join(' '),
            x: box.x,
            y: box.y,
            width: box.width,
            height: box.height,
            rx: 8,
            ry: 8,
            'pointer-events': 'none',
          });
          if (inlineStyles) {
            const stroke = elementLinks.length ? '#6f42c1' : '#b58100';
            marker.setAttribute('fill', 'rgba(111, 66, 193, 0.025)');
            marker.setAttribute('stroke', stroke);
            marker.setAttribute('stroke-width', '2');
            marker.setAttribute('stroke-dasharray', '6 4');
            marker.setAttribute('style', `pointer-events:none;fill:rgba(111, 66, 193, 0.025);stroke:${stroke};stroke-width:2;stroke-dasharray:6 4;`);
          }
          marker.style.pointerEvents = 'none';
          layer.appendChild(marker);
        }
        drawCommentPill(layer, target, box, elementComments, options.onCommentClick);
        if (showLinkPills && (index === 0 || target.kind !== 'participant')) drawLinkPill(layer, target, box, elementLinks);
      });
    });
    return targets;
  }

  window.MIDENA_RENDERED = { applySvgInteractions, discoverTargets, makeElementId };
})();
