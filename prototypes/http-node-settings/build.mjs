import * as esbuild from 'esbuild';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const directory = path.dirname(fileURLToPath(import.meta.url));
const outputDirectory = path.resolve(directory, '../../web/static/assets');

await esbuild.build({
    entryPoints: [path.join(directory, 'prototype.jsx')],
    bundle: true,
    minify: false,
    sourcemap: false,
    loader: {'.js': 'jsx', '.jsx': 'jsx'},
    outfile: path.join(outputDirectory, 'http-node-prototype.js'),
    jsx: 'automatic',
});
