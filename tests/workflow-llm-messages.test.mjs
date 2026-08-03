import test from 'node:test';
import assert from 'node:assert/strict';

import {
    trimTrailingEmptyLlmMessages,
    trimTrailingEmptyLlmNodeMessages,
} from '../web/frontend/workflow-llm-messages.mjs';

const message = (role, content) => ({role, content});

test('removes trailing empty ASSISTANT and USER messages after the fixed pair', () => {
    const messages = [
        message('SYSTEM', ''),
        message('USER', '问题'),
        message('ASSISTANT', ''),
        message('USER', ' \n\t '),
    ];

    assert.deepEqual(trimTrailingEmptyLlmMessages(messages), messages.slice(0, 2));
});

test('removes a trailing empty ASSISTANT while preserving the fixed messages', () => {
    const messages = [
        message('SYSTEM', ''),
        message('USER', ''),
        message('ASSISTANT', '\n'),
    ];

    assert.deepEqual(trimTrailingEmptyLlmMessages(messages), messages.slice(0, 2));
});

test('keeps an empty ASSISTANT when a non-empty USER follows it', () => {
    const messages = [
        message('SYSTEM', ''),
        message('USER', '问题'),
        message('ASSISTANT', ''),
        message('USER', '不得丢失的内容'),
    ];

    assert.equal(trimTrailingEmptyLlmMessages(messages), messages);
});

test('leaves non-LLM nodes and complete LLM drafts unchanged', () => {
    const scriptNode = {data: {nodeType: 'SCRIPT'}};
    const messages = [message('SYSTEM', ''), message('USER', '问题')];
    const llmNode = {data: {nodeType: 'LLM', llmMessages: messages}};

    assert.equal(trimTrailingEmptyLlmNodeMessages(scriptNode), scriptNode);
    assert.equal(trimTrailingEmptyLlmNodeMessages(llmNode), llmNode);
});
