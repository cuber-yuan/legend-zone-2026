import { mkdir, copyFile, readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
const require = createRequire(import.meta.url);
const postcss = require('postcss'),
  tailwind = require('tailwindcss');
const web = new URL('../', import.meta.url),
  out = new URL('../../server/static/', import.meta.url);
await mkdir(new URL('vendor/', out), { recursive: true });
const config = require('../tailwind.config.cjs');
config.content = config.content.map((value) => fileURLToPath(new URL(value, web)));
const css = await postcss([tailwind(config)]).process(
  await readFile(new URL('styles/app.css', web), 'utf8'),
  { from: undefined },
);
await import('node:fs/promises').then((fs) => fs.writeFile(new URL('app.css', out), css.css));
for (const [source, target] of [
  ['phaser/dist/phaser.js', 'phaser.js'],
  ['prismjs/prism.js', 'prism.js'],
  ['prismjs/components/prism-python.min.js', 'prism-python.js'],
  ['prismjs/themes/prism.css', 'prism.css'],
])
  await copyFile(new URL('node_modules/' + source, web), new URL('vendor/' + target, out));
console.log('Built existing UI styles and local runtime assets.');
