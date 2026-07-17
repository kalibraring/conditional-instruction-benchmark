const fs = require('node:fs');
const path = require('node:path');

async function extensionHook(hookName, context) {
  if (hookName !== 'afterEach') {
    return context;
  }
  const metadata = context.test?.metadata || {};
  const trialId = metadata.trial_id;
  const rawDir = metadata.raw_dir;
  if (!trialId || !rawDir) {
    throw new Error('CIB archive metadata is incomplete');
  }
  fs.mkdirSync(rawDir, { recursive: true });
  const target = path.join(rawDir, `${trialId}.json`);
  const temporary = `${target}.tmp-${process.pid}`;
  fs.writeFileSync(
    temporary,
    JSON.stringify({ test: context.test, result: context.result }, null, 2),
    { encoding: 'utf8', flag: 'wx' },
  );
  fs.renameSync(temporary, target);
  return context;
}

module.exports = extensionHook;
