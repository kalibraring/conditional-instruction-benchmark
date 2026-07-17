const { spawnSync } = require('node:child_process');

module.exports = (output, context) => {
  const child = spawnSync(
    process.env.CIB_PYTHON || 'python3',
    ['-m', 'cib.assertion_bridge'],
    {
      input: JSON.stringify({ output, context }),
      encoding: 'utf8',
      env: process.env,
      maxBuffer: 64 * 1024 * 1024,
    },
  );
  if (child.status !== 0) {
    throw new Error(`CIB assertion bridge failed: ${child.stderr || child.stdout}`);
  }
  return JSON.parse(child.stdout);
};
