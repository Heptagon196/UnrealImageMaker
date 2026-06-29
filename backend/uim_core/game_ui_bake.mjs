import { chromium } from "playwright";

const chunks = [];
for await (const chunk of process.stdin) {
  chunks.push(chunk);
}

const input = JSON.parse(Buffer.concat(chunks).toString("utf8"));
const { html, width, height, allowedTypes } = input;

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
  await page.setContent(html, { waitUntil: "load" });
  await page.waitForTimeout(100);
  const result = await page.evaluate(
    ([allowedTypesValue, expectedWidth, expectedHeight]) => {
      const allowed = new Set(allowedTypesValue);
      const root = document.querySelector('[data-u-type="screen"][data-u-name]');
      if (!root) throw new Error('Missing root node: data-u-type="screen" and data-u-name are required.');
      const seen = new Set();
      const rootRect = root.getBoundingClientRect();
      function rgb2hex(value) {
        if (!value || value === "transparent" || value === "rgba(0, 0, 0, 0)") return "#FFFFFF00";
        const match = value.match(/^rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)$/);
        if (!match) return value;
        const hex = (n) => (`0${Number(n).toString(16)}`).slice(-2);
        const alpha = match[4] === undefined ? "" : hex(Math.round(Number(match[4]) * 255));
        return `#${hex(match[1])}${hex(match[2])}${hex(match[3])}${alpha}`;
      }
      function parseNumber(value, fallback) {
        const parsed = Number.parseFloat(value);
        return Number.isFinite(parsed) ? parsed : fallback;
      }
      function parsePivot(value, nodeName) {
        const presets = {
          "top-left": [0, 0],
          top: [0.5, 0],
          "top-right": [1, 0],
          left: [0, 0.5],
          center: [0.5, 0.5],
          right: [1, 0.5],
          "bottom-left": [0, 1],
          bottom: [0.5, 1],
          "bottom-right": [1, 1]
        };
        const text = String(value || "").trim().toLowerCase();
        if (presets[text]) return presets[text];
        const parts = text.split(",").map((part) => part.trim());
        if (parts.length !== 2) throw new Error(`UI node "${nodeName}" has invalid data-u-pivot.`);
        const pivotX = Number(parts[0]);
        const pivotY = Number(parts[1]);
        if (!Number.isFinite(pivotX) || !Number.isFinite(pivotY) || pivotX < 0 || pivotX > 1 || pivotY < 0 || pivotY > 1) {
          throw new Error(`UI node "${nodeName}" has invalid data-u-pivot. Pivot values must be between 0 and 1.`);
        }
        return [pivotX, pivotY];
      }
      function layoutForPreset(preset, x, y, widthValue, heightValue, rootWidth, rootHeight, pivot) {
        const anchorsByPreset = {
          "top-left": [0, 0, 0, 0],
          "top-right": [1, 0, 1, 0],
          "bottom-left": [0, 1, 0, 1],
          "bottom-right": [1, 1, 1, 1],
          center: [0.5, 0.5, 0.5, 0.5],
          "top-stretch": [0, 0, 1, 0],
          "bottom-stretch": [0, 1, 1, 1],
          "left-stretch": [0, 0, 0, 1],
          "right-stretch": [1, 0, 1, 1],
          full: [0, 0, 1, 1]
        };
        const normalized = String(preset || "top-left").trim().toLowerCase();
        const values = anchorsByPreset[normalized] || anchorsByPreset["top-left"];
        const [minX, minY, maxX, maxY] = values;
        const [pivotX, pivotY] = pivot || [0, 0];
        return {
          anchorPreset: anchorsByPreset[normalized] ? normalized : "top-left",
          anchors: { minimum: { x: minX, y: minY }, maximum: { x: maxX, y: maxY } },
          offsets: {
            left: Math.round(x - minX * rootWidth + (minX === maxX ? widthValue * pivotX : 0)),
            top: Math.round(y - minY * rootHeight + (minY === maxY ? heightValue * pivotY : 0)),
            right: Math.round(minX === maxX ? widthValue : maxX * rootWidth - (x + widthValue)),
            bottom: Math.round(minY === maxY ? heightValue : maxY * rootHeight - (y + heightValue))
          },
          alignment: { x: pivotX, y: pivotY }
        };
      }
      function inferAnchorPreset(element, style, x, y, widthValue, heightValue, rootWidth, rootHeight) {
        const allowedAnchors = new Set([
          "top-left",
          "top-right",
          "bottom-left",
          "bottom-right",
          "center",
          "top-stretch",
          "bottom-stretch",
          "left-stretch",
          "right-stretch",
          "full"
        ]);
        const explicit = element.getAttribute("data-u-anchor");
        if (!explicit) throw new Error(`UI node "${element.getAttribute("data-u-name") || ""}" must include explicit data-u-anchor.`);
        const normalized = explicit.trim().toLowerCase();
        if (!allowedAnchors.has(normalized)) throw new Error(`Unsupported data-u-anchor on "${element.getAttribute("data-u-name") || ""}": ${explicit}`);
        return normalized;
      }
      function bake(element) {
        const type = element.getAttribute("data-u-type");
        const name = element.getAttribute("data-u-name");
        if (!type && !name) return null;
        if (!type || !name) throw new Error("Every exported node must include both data-u-type and data-u-name.");
        if (!allowed.has(type)) throw new Error(`Unsupported data-u-type: ${type}`);
        if (seen.has(name)) throw new Error(`Duplicate data-u-name: ${name}`);
        seen.add(name);
        const rect = element.getBoundingClientRect();
        const style = window.getComputedStyle(element);
        const children = [];
        for (const child of Array.from(element.children)) {
          if (element.tagName.toLowerCase() === "select" && child.tagName.toLowerCase() === "option") continue;
          const baked = bake(child);
          if (baked) children.push(baked);
        }
        const options = [];
        if (type === "dropdown" && element.tagName.toLowerCase() === "select") {
          for (const option of Array.from(element.querySelectorAll("option"))) options.push(option.innerText.trim());
        }
        const x = Math.round(rect.left - rootRect.left);
        const y = Math.round(rect.top - rootRect.top);
        const nodeWidth = Math.round(rect.width);
        const nodeHeight = Math.round(rect.height);
        const anchorPreset = type === "screen" ? "full" : inferAnchorPreset(element, style, x, y, nodeWidth, nodeHeight, rootRect.width || expectedWidth, rootRect.height || expectedHeight);
        const pivot = type === "screen" ? [0, 0] : parsePivot(element.getAttribute("data-u-pivot"), name);
        const layout = layoutForPreset(anchorPreset, x, y, nodeWidth, nodeHeight, rootRect.width || expectedWidth, rootRect.height || expectedHeight, pivot);
        return {
          name,
          type,
          styleToken: element.getAttribute("data-u-style-token") || "",
          x,
          y,
          width: nodeWidth,
          height: nodeHeight,
          anchorPreset: layout.anchorPreset,
          anchors: layout.anchors,
          offsets: layout.offsets,
          alignment: layout.alignment,
          color: rgb2hex(style.backgroundColor),
          fontColor: rgb2hex(style.color),
          fontSize: Math.round(parseNumber(style.fontSize, 16)),
          fontWeight: style.fontWeight || "",
          textAlign: style.textAlign || "center",
          text: (type === "input" ? element.value || element.placeholder || "" : ["text", "button", "dropdown"].includes(type) ? element.innerText || "" : "").trim(),
          value: parseNumber(element.getAttribute("data-u-value"), 0.5),
          checked: element.getAttribute("data-u-checked") === "true",
          direction: element.getAttribute("data-u-dir") || "v",
          options,
          children
        };
      }
      return {
        width: Math.round(rootRect.width) || expectedWidth,
        height: Math.round(rootRect.height) || expectedHeight,
        root: bake(root)
      };
    },
    [allowedTypes, width, height]
  );
  process.stdout.write(JSON.stringify(result));
} finally {
  await browser.close();
}
