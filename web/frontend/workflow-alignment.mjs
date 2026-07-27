export const ALIGNMENT_GUIDE_THRESHOLD = 5;

function nodeWidth(node) {
    return Number(node?.measured?.width || node?.width || 236);
}

function nodeHeight(node) {
    return Number(node?.measured?.height || node?.height || 112);
}

function isWithinAlignmentThreshold(first, second, threshold) {
    const difference = Math.ceil(first) - Math.ceil(second);
    return difference < threshold && difference > -threshold;
}

export function calculateAlignmentGuides(nodes, draggingNode, threshold = ALIGNMENT_GUIDE_THRESHOLD) {
    if (!draggingNode?.position || !Array.isArray(nodes)) return null;

    const candidates = nodes.filter((node) => node.id !== draggingNode.id && node.position);
    const horizontalNodes = candidates.filter((node) => (
        isWithinAlignmentThreshold(node.position.y, draggingNode.position.y, threshold)
    ));
    const verticalNodes = candidates.filter((node) => (
        isWithinAlignmentThreshold(node.position.x, draggingNode.position.x, threshold)
    ));

    const horizontal = horizontalNodes.length ? (() => {
        const aligned = [draggingNode, ...horizontalNodes];
        const left = Math.min(...aligned.map((node) => node.position.x));
        const right = Math.max(...aligned.map((node) => node.position.x + nodeWidth(node)));
        return {
            top: horizontalNodes[0].position.y,
            left,
            width: right - left,
        };
    })() : null;

    const vertical = verticalNodes.length ? (() => {
        const aligned = [draggingNode, ...verticalNodes];
        const top = Math.min(...aligned.map((node) => node.position.y));
        const bottom = Math.max(...aligned.map((node) => node.position.y + nodeHeight(node)));
        return {
            top,
            left: verticalNodes[0].position.x,
            height: bottom - top,
        };
    })() : null;

    return horizontal || vertical ? {horizontal, vertical} : null;
}
