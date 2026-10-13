import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import test from "node:test";
import vm from "node:vm";

const source = stripTypeScriptTypes(readFileSync(new URL("../../../fresh/init.ts", import.meta.url), "utf8"));

function setup(path) {
  const handlers = new Map();
  let clipboard = "previous clipboard";
  const editor = {
    getEnv: () => null,
    on: () => {},
    registerCommand: () => {},
    getActiveBufferId: () => 7,
    getBufferPath: bufferId => {
      assert.equal(bufferId, 7);
      return path;
    },
    setClipboard: value => { clipboard = value; },
    setStatus: () => {},
  };
  vm.runInNewContext(source, { editor, registerHandler: (name, fn) => handlers.set(name, fn) });
  return { copyPath: handlers.get("dotfiles_copy_file_path"), clipboard: () => clipboard };
}

test("copy path writes the active file's path to the clipboard", () => {
  const state = setup("/project/example.txt");
  state.copyPath();
  assert.equal(state.clipboard(), "/project/example.txt");
});

test("an unnamed buffer leaves clipboard content intact", () => {
  for (const path of [null, ""]) {
    const state = setup(path);
    state.copyPath();
    assert.equal(state.clipboard(), "previous clipboard");
  }
});
