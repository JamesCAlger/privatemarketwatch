const fs = require("fs");

const originalRealpathSync = fs.realpathSync;
const originalNativeRealpathSync = fs.realpathSync.native;

function fallbackOnEperm(fn) {
  return function realpathWithSandboxFallback(path, ...args) {
    try {
      return fn.call(this, path, ...args);
    } catch (error) {
      if (error && error.code === "EPERM") {
        return path;
      }
      throw error;
    }
  };
}

fs.realpathSync = fallbackOnEperm(originalRealpathSync);
fs.realpathSync.native = fallbackOnEperm(originalNativeRealpathSync);
