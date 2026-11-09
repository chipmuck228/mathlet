import { cpSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
const root = fileURLToPath(new URL('../', import.meta.url));
const target = resolve(root, 'apps/web/public/mathlive');
mkdirSync(target, { recursive: true });
cpSync(resolve(root, 'node_modules/mathlive/fonts'), resolve(target, 'fonts'), { recursive: true });
cpSync(resolve(root, 'node_modules/mathlive/LICENSE.txt'), resolve(target, 'MathLive-LICENSE.txt'));
