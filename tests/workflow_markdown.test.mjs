import test from 'node:test';
import assert from 'node:assert/strict';

import {
    createTemplateVariablePattern,
    templateVariableRanges,
} from '../web/frontend/workflow-markdown.mjs';

test('finds root, nested, and indexed workflow template variables', () => {
    const source = '${question}\n${payload.name}\n${items[0].title}';

    assert.deepEqual(
        templateVariableRanges(source).map((range) => range.text),
        ['${question}', '${payload.name}', '${items[0].title}'],
    );
});

test('ignores escaped and malformed workflow template variables', () => {
    const source = '\\${question} ${9invalid} ${payload.} ${items[-1]} ${valid_name}';

    assert.deepEqual(
        templateVariableRanges(source).map((range) => range.text),
        ['${valid_name}'],
    );
});

test('reports exact ranges without changing multilingual prompt text', () => {
    const source = '# 标题 ✨\n\n使用 `${payload.items[0]}`。';
    const snapshot = source;
    const [range] = templateVariableRanges(source);

    assert.equal(source, snapshot);
    assert.equal(source.slice(range.from, range.to), '${payload.items[0]}');
    assert.equal(createTemplateVariablePattern().test(source), true);
});
