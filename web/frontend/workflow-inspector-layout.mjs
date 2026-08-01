export function clampInspectorPosition({
    x,
    y,
    width,
    height,
    parentWidth,
    parentHeight,
    margin = 14,
}) {
    const maxX = Math.max(margin, parentWidth - width - margin);
    const maxY = Math.max(margin, parentHeight - height - margin);
    return {
        x: Math.max(margin, Math.min(x, maxX)),
        y: Math.max(margin, Math.min(y, maxY)),
    };
}
