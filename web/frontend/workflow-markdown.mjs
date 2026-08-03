const TEMPLATE_VARIABLE_SOURCE = String.raw`(?<!\\)\$\{[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*|\[[0-9]+\])*\}`;

export function createTemplateVariablePattern() {
    return new RegExp(TEMPLATE_VARIABLE_SOURCE, 'g');
}

export function templateVariableRanges(value) {
    const text = String(value ?? '');
    return Array.from(text.matchAll(createTemplateVariablePattern()), (match) => ({
        from: match.index,
        to: match.index + match[0].length,
        text: match[0],
    }));
}
