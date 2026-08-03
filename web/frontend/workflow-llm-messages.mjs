export function trimTrailingEmptyLlmMessages(messages, preservedCount = 2) {
    if (!Array.isArray(messages) || messages.length <= preservedCount) return messages;
    let nextLength = messages.length;
    while (
        nextLength > preservedCount
        && !String(messages[nextLength - 1]?.content ?? '').trim()
    ) {
        nextLength -= 1;
    }
    return nextLength === messages.length ? messages : messages.slice(0, nextLength);
}

export function trimTrailingEmptyLlmNodeMessages(node) {
    if (node?.data?.nodeType !== 'LLM') return node;
    const messages = node.data.llmMessages;
    const trimmed = trimTrailingEmptyLlmMessages(messages);
    if (trimmed === messages) return node;
    return {
        ...node,
        data: {...node.data, llmMessages: trimmed},
    };
}
