const SVG_NS = "http://www.w3.org/2000/svg";
const MAN_NUMERALS = ["一", "二", "三", "四", "五", "六", "七", "八", "九"];
const HONORS = ["東", "南", "西", "北", "白", "發", "中"];

const PIN_LAYOUTS = {
  2: [[50, 38], [50, 92]],
  3: [[30, 30], [50, 65], [70, 100]],
  4: [[31, 36], [69, 36], [31, 94], [69, 94]],
  5: [[29, 30], [71, 30], [50, 65], [29, 100], [71, 100]],
  6: [[31, 27], [69, 27], [31, 65], [69, 65], [31, 103], [69, 103]],
  7: [[27, 27], [50, 27], [73, 27], [34, 65], [66, 65], [34, 101], [66, 101]],
  8: [[31, 21], [69, 21], [31, 50], [69, 50], [31, 80], [69, 80], [31, 109], [69, 109]],
  9: [[25, 25], [50, 25], [75, 25], [25, 65], [50, 65], [75, 65], [25, 105], [50, 105], [75, 105]],
};

const SOU_LAYOUTS = {
  2: [[39, 36], [61, 92]],
  3: [[33, 30], [67, 30], [50, 91]],
  4: [[34, 34], [66, 34], [34, 94], [66, 94]],
  5: [[30, 29], [70, 29], [50, 65], [30, 101], [70, 101]],
  6: [[31, 27], [69, 27], [31, 65], [69, 65], [31, 103], [69, 103]],
  7: [[28, 24], [50, 24], [72, 24], [35, 63], [65, 63], [35, 102], [65, 102]],
  8: [[31, 21], [69, 21], [31, 50], [69, 50], [31, 80], [69, 80], [31, 109], [69, 109]],
  9: [[25, 24], [50, 24], [75, 24], [25, 65], [50, 65], [75, 65], [25, 106], [50, 106], [75, 106]],
};

export function tileType(id) { return Math.floor(Number(id) / 4); }

export function tileSuit(id) {
  const type = tileType(id);
  return type < 9 ? "man" : type < 18 ? "pin" : type < 27 ? "sou" : "honor";
}

export function tileLabel(id) {
  const type = tileType(id);
  if (type < 9) return `${type + 1}萬`;
  if (type < 18) return `${type - 8}筒`;
  if (type < 27) return `${type - 17}索`;
  return HONORS[type - 27];
}

export function tileFaceSpec(type) {
  if (!Number.isInteger(type) || type < 0 || type > 33) throw new RangeError("mahjong tile type must be 0-33");
  if (type < 9) return {kind: "man", rank: type + 1, label: `${MAN_NUMERALS[type]}萬`};
  if (type < 18) {
    const rank = type - 8;
    return {kind: "pin", rank, label: `${rank}筒`, marks: rank === 1 ? [[50, 65]] : PIN_LAYOUTS[rank]};
  }
  if (type < 27) {
    const rank = type - 17;
    return {kind: "sou", rank, label: `${rank}索`, marks: rank === 1 ? [[50, 65]] : SOU_LAYOUTS[rank]};
  }
  return {kind: "honor", rank: type - 26, label: HONORS[type - 27]};
}

function svgNode(documentRef, name, attributes = {}, text = "") {
  const node = documentRef.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  if (text) node.textContent = text;
  return node;
}

function drawPinOne(svg, documentRef) {
  const group = svgNode(documentRef, "g", {class: "pin-one", transform: "translate(50 65)"});
  group.append(svgNode(documentRef, "circle", {class: "pin-one-outer", r: 25}));
  for (let angle = 0; angle < 360; angle += 45) {
    group.append(svgNode(documentRef, "ellipse", {class: `pin-one-petal petal-${angle / 45}`, cx: 0, cy: -14, rx: 5.2, ry: 10.5, transform: `rotate(${angle})`}));
  }
  group.append(
    svgNode(documentRef, "circle", {class: "pin-one-ring", r: 11.5}),
    svgNode(documentRef, "circle", {class: "pin-one-core", r: 5}),
  );
  svg.append(group);
}

function drawPin(svg, documentRef, mark, index, rank) {
  const [x, y] = mark;
  const tone = rank === 5 && index === 2 ? "red" : index % 3 === 1 ? "green" : "blue";
  const group = svgNode(documentRef, "g", {class: `pin-dot tone-${tone}`, transform: `translate(${x} ${y})`});
  group.append(
    svgNode(documentRef, "circle", {class: "pin-rim", r: 10}),
    svgNode(documentRef, "circle", {class: "pin-petal", r: 6.2}),
    svgNode(documentRef, "circle", {class: "pin-core", r: 2.4}),
  );
  svg.append(group);
}

function drawBird(svg, documentRef) {
  const bird = svgNode(documentRef, "g", {class: "sou-bird"});
  bird.append(
    svgNode(documentRef, "path", {class: "bird-branch", d: "M16 105 Q47 93 84 103"}),
    svgNode(documentRef, "path", {class: "bird-tail", d: "M35 80 Q20 98 24 112 Q36 101 43 87 Z"}),
    svgNode(documentRef, "ellipse", {class: "bird-body", cx: 50, cy: 72, rx: 22, ry: 31, transform: "rotate(-12 50 72)"}),
    svgNode(documentRef, "path", {class: "bird-wing", d: "M35 65 Q50 54 64 69 Q51 91 35 88 Q43 77 35 65 Z"}),
    svgNode(documentRef, "circle", {class: "bird-head", cx: 65, cy: 42, r: 13}),
    svgNode(documentRef, "circle", {class: "bird-eye", cx: 69, cy: 39, r: 2.2}),
    svgNode(documentRef, "path", {class: "bird-beak", d: "M77 43 L90 48 L77 52 Z"}),
    svgNode(documentRef, "path", {class: "bird-crest", d: "M56 31 Q59 18 67 28 Q72 17 74 32"}),
    svgNode(documentRef, "path", {class: "bird-feet", d: "M45 99 l-4 8 m8-8 l2 8 m10-11 l-2 9 m6-11 l3 8"}),
  );
  svg.append(bird);
}

function drawBamboo(svg, documentRef, mark, index, rank) {
  const [x, y] = mark;
  const red = (rank === 5 && index === 2) || (rank === 7 && index === 3) || (rank === 9 && index === 4);
  const angle = index % 2 === 0 ? -4 : 4;
  const group = svgNode(documentRef, "g", {class: `bamboo-stick ${red ? "tone-red" : "tone-green"}`, transform: `translate(${x} ${y}) rotate(${angle})`});
  for (const offset of [-17, -5, 7]) {
    group.append(svgNode(documentRef, "rect", {class: "bamboo-segment", x: -4.5, y: offset, width: 9, height: 10.5, rx: 4}));
  }
  group.append(
    svgNode(documentRef, "path", {class: "bamboo-highlight", d: "M-1 -14 L-1 14"}),
    svgNode(documentRef, "path", {class: "bamboo-leaf", d: "M4 -12 Q12 -18 12 -7 Q7 -6 4 -2"}),
  );
  svg.append(group);
}

export function createTileFace(id, documentRef = document) {
  const spec = tileFaceSpec(tileType(id));
  const svg = svgNode(documentRef, "svg", {
    class: `tile-face ${spec.kind}-face`,
    viewBox: "0 0 100 130",
    preserveAspectRatio: "xMidYMid meet",
    "aria-hidden": "true",
    focusable: "false",
    "data-kind": spec.kind,
    "data-rank": spec.rank,
  });

  if (spec.kind === "man") {
    svg.append(
      svgNode(documentRef, "text", {class: "mahjong-glyph man-number", x: 50, y: 67, "text-anchor": "middle"}, MAN_NUMERALS[spec.rank - 1]),
      svgNode(documentRef, "text", {class: "mahjong-glyph man-suit", x: 50, y: 108, "text-anchor": "middle"}, "萬"),
    );
  } else if (spec.kind === "pin") {
    if (spec.rank === 1) drawPinOne(svg, documentRef);
    else spec.marks.forEach((mark, index) => drawPin(svg, documentRef, mark, index, spec.rank));
  } else if (spec.kind === "sou") {
    if (spec.rank === 1) drawBird(svg, documentRef);
    else spec.marks.forEach((mark, index) => drawBamboo(svg, documentRef, mark, index, spec.rank));
  } else if (spec.label === "白") {
    svg.append(
      svgNode(documentRef, "rect", {class: "white-dragon-frame", x: 21, y: 27, width: 58, height: 76, rx: 8}),
      svgNode(documentRef, "rect", {class: "white-dragon-inner", x: 28, y: 34, width: 44, height: 62, rx: 5}),
    );
  } else {
    const className = spec.label === "發" ? "honor-green" : spec.label === "中" ? "honor-red" : "honor-wind";
    svg.append(svgNode(documentRef, "text", {class: `mahjong-glyph honor-glyph ${className}`, x: 50, y: 86, "text-anchor": "middle"}, spec.label));
  }
  return svg;
}
