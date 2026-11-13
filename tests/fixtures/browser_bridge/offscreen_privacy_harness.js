const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const context = {console};
context.globalThis = context;
const drawing = [];
context.Image = class {
  naturalWidth = 200;
  naturalHeight = 100;
  async decode() { drawing.push(["decode"]); }
};
context.document = {
  createElement(name) {
    assert.equal(name, "canvas");
    const canvas = {width: 0, height: 0};
    canvas.getContext = () => ({
      drawImage: (...args) => drawing.push(["drawImage", ...args.slice(1)]),
      set fillStyle(value) { drawing.push(["fillStyle", value]); },
      fillRect: (...args) => drawing.push(["fillRect", ...args]),
    });
    canvas.toDataURL = (type) => { drawing.push(["toDataURL", type]); return "data:image/png;base64,masked"; };
    return canvas;
  },
};
vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), context);

const scaled = context.scaleRedactionRegions(
  [{x: 10, y: 5, width: 20, height: 10}],
  {width: 100, height: 50},
  200,
  100,
);
assert.deepEqual(JSON.parse(JSON.stringify(scaled)), [{x: 20, y: 10, width: 40, height: 20}]);
assert.throws(() => context.scaleRedactionRegions([{x: -1, y: 0, width: 2, height: 2}], {width: 10, height: 10}, 10, 10), /invalid redaction region/);
assert.throws(() => context.scaleRedactionRegions([{x: 9, y: 0, width: 2, height: 2}], {width: 10, height: 10}, 10, 10), /outside viewport/);
(async () => {
  const masked = await context.maskScreenshot(
    "data:image/png;base64,fixture",
    [{x: 10, y: 5, width: 20, height: 10}],
    {width: 100, height: 50},
  );
  assert.deepEqual(JSON.parse(JSON.stringify(masked)), {dataUrl: "data:image/png;base64,masked", maskedRegions: 1});
  assert.deepEqual(drawing, [
    ["decode"], ["drawImage", 0, 0], ["fillStyle", "#000000"],
    ["fillRect", 20, 10, 40, 20], ["toDataURL", "image/png"],
  ]);
  process.stdout.write(JSON.stringify({success: true, cases: ["scaled-device-pixels", "reject-negative-region", "reject-outside-region", "opaque-pixel-mask"]}));
})().catch((error) => { process.stderr.write(String(error)); process.exitCode = 1; });
