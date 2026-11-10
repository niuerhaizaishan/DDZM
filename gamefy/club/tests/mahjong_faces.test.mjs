import assert from "node:assert/strict";
import test from "node:test";

import {tileFaceSpec, tileLabel, tileSuit} from "../publish/mahjong-faces.js";

test("all 34 mahjong faces are uniquely labeled and assigned to the correct suit", () => {
  const specs = Array.from({length: 34}, (_, type) => tileFaceSpec(type));
  assert.equal(new Set(specs.map(spec => spec.label)).size, 34);
  assert.deepEqual(specs.map(spec => spec.kind).reduce((counts, kind) => ({...counts, [kind]: (counts[kind] || 0) + 1}), {}), {
    man: 9,
    pin: 9,
    sou: 9,
    honor: 7,
  });
});

test("dot and bamboo faces expose the expected number of marks", () => {
  for (const type of [9, 10, 11, 12, 13, 14, 15, 16, 18, 19, 20, 21, 22, 23, 24, 25]) {
    const spec = tileFaceSpec(type);
    assert.equal(spec.marks.length, spec.rank, spec.label);
  }
  assert.deepEqual(tileFaceSpec(9).marks, [[50, 65]]);
  assert.deepEqual(tileFaceSpec(18).marks, [[50, 65]]);
});

test("tile ids keep the public labels and suits used by the game", () => {
  assert.equal(tileLabel(0), "1萬");
  assert.equal(tileLabel(36), "1筒");
  assert.equal(tileLabel(72), "1索");
  assert.equal(tileLabel(124), "白");
  assert.equal(tileSuit(132), "honor");
});
