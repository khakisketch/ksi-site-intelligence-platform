import { realpathSync } from "node:fs";
import path from "node:path";

// A linked worktree may borrow node_modules from the main checkout. Both the
// bundler and NFT copier need the *real* dependency location inside their root.
// Ordinary installs (including the Docker builder) keep the app-local layout.
export function dashboardBuildRoot(projectRoot) {
  let root = realpathSync(projectRoot);
  const modules = realpathSync(path.join(root, "node_modules"));
  while (!inside(root, modules)) {
    const parent = path.dirname(root);
    if (parent === root || parent === path.parse(root).root) {
      throw new Error("Dashboard dependencies must share a non-filesystem build root with the app.");
    }
    root = parent;
  }
  return root;
}

function inside(root, target) {
  const relative = path.relative(root, target);
  return relative === "" || (!path.isAbsolute(relative) && relative !== ".." && !relative.startsWith(`..${path.sep}`));
}
